"""Search the U.S. federal open data catalog (catalog.data.gov) for datasets.

``catalog.data.gov`` is the public dataset-discovery portal for Data.gov.  It
harvests metadata from hundreds of federal, state, local, tribal, university
and non-profit publishers and exposes a public, keyless full-text search API
that replaced the legacy CKAN action API in 2025::

    GET https://catalog.data.gov/search?q=QUERY&per_page=N

The response is ``{"results": [...], "sort": "relevance", "after": <cursor>}``.
Every result carries the dataset ``title`` and ``description``, the harvesting
``organization``, a free-text ``publisher``, subject ``keyword`` and ``theme``
lists, the ``distribution_titles`` (download formats), the ``identifier`` and
canonical ``slug``, plus the ``last_harvested_date``, ``popularity`` score and
public access level.

This complements the European open data portal provider with a catalogue of
U.S. public-sector datasets: it answers which official dataset covers a
subject, who publishes it, and in which formats it can be downloaded.  No API
key is required.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://catalog.data.gov/search"
# Human-readable dataset page.
_DATASET_PAGE_URL = "https://catalog.data.gov/dataset/"
# The catalog pages its result lists; keep pages small for agents.
_MAX_API_RESULTS = 50
# Characters of the dataset description copied into the snippet.
_SNIPPET_DESCRIPTION_LENGTH = 180
# Keyword, theme and distribution-format values listed before an ellipsis.
_SNIPPET_KEYWORD_LIMIT = 5
_SNIPPET_THEME_LIMIT = 3
_SNIPPET_FORMAT_LIMIT = 4


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _string_list(value: object, limit: int) -> list[str]:
    """Return a deduplicated list of non-empty strings from *value*.

    Only string entries are kept, preserving order and capping the result at
    *limit* items.
    """
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for entry in value:
        label = _clean(entry)
        if label and label not in items:
            items.append(label)
        if len(items) >= limit:
            break
    return items


class UsOpenDataProvider(BaseProvider):
    """Search the U.S. federal open data catalog for public-sector datasets.

    Keyless.  Queries the catalog.data.gov search API in a single request and
    returns one hit per dataset, carrying the title, description, publishing
    organization, publisher, keywords, themes, distribution formats and
    popularity, and linking to the dataset page on catalog.data.gov.
    """

    name = "us_open_data"
    description = (
        "Search catalog.data.gov — the U.S. federal open data catalog — for "
        "public-sector datasets from federal, state, local, tribal, university "
        "and non-profit publishers (title, description, organization, "
        "publisher, keywords, themes, distribution formats, popularity) via "
        "the keyless Catalog API, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "gov", "data", "knowledge"]

    @staticmethod
    def _organization(item: dict[str, Any]) -> str:
        """Return the harvesting organization's name."""
        organization = item.get("organization")
        if isinstance(organization, dict):
            return _clean(organization.get("name"))
        return _clean(organization)

    @staticmethod
    def _description(item: dict[str, Any]) -> str:
        """Return the dataset description, falling back to its DCAT copy."""
        description = _clean(item.get("description"))
        if description:
            return description
        dcat = item.get("dcat")
        if isinstance(dcat, dict):
            return _clean(dcat.get("description"))
        return ""

    @staticmethod
    def _snippet(
        description: str,
        publisher: str,
        organization: str,
        keywords: list[str],
        themes: list[str],
        formats: list[str],
        popularity: int,
    ) -> str:
        """Compose the snippet for a single dataset."""
        parts: list[str] = []
        if description:
            parts.append(description[:_SNIPPET_DESCRIPTION_LENGTH])
        if publisher:
            parts.append(f"Publisher: {publisher}")
        if organization:
            parts.append(f"Organization: {organization}")
        if keywords:
            parts.append(f"Keywords: {', '.join(keywords)}")
        if themes:
            parts.append(f"Themes: {', '.join(themes)}")
        if formats:
            parts.append(f"Formats: {', '.join(formats)}")
        if popularity:
            parts.append(f"Popularity: {popularity}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw catalog record."""
        title = _clean(item.get("title"))
        if not title:
            return None

        slug = _clean(item.get("slug"))
        identifier = _clean(item.get("identifier"))
        if slug:
            url = f"{_DATASET_PAGE_URL}{quote(slug, safe='')}"
        elif identifier.startswith("http"):
            url = identifier
        else:
            return None

        publisher = _clean(item.get("publisher"))
        organization = self._organization(item)
        keywords = _string_list(item.get("keyword"), _SNIPPET_KEYWORD_LIMIT)
        themes = _string_list(item.get("theme"), _SNIPPET_THEME_LIMIT)
        formats = _string_list(
            item.get("distribution_titles"),
            _SNIPPET_FORMAT_LIMIT,
        )
        popularity = item.get("popularity")
        popularity = popularity if isinstance(popularity, int) else 0
        harvested = _clean(item.get("last_harvested_date"))
        updated = harvested[:10] if harvested else ""

        return SearchResult(
            title=title,
            url=url,
            snippet=self._snippet(
                self._description(item),
                publisher,
                organization,
                keywords,
                themes,
                formats,
                popularity,
            ),
            source="catalog.data.gov",
            rank=rank,
            provider=self.name,
            published_date=updated or None,
            extra={
                "id": identifier or None,
                "slug": slug or None,
                "organization": organization or None,
                "publisher": publisher or None,
                "keywords": keywords,
                "themes": themes,
                "formats": formats,
                "popularity": popularity,
                "access_level": _clean(item.get("access_level")) or None,
                "has_download": bool(item.get("has_download")),
                "has_spatial": bool(item.get("has_spatial")),
                "updated": updated or None,
            },
        )

    def _parse(self, data: object, limit: int) -> list[SearchResult]:
        """Parse a catalog search response, deduplicating hits by dataset id."""
        if not isinstance(data, dict):
            return []
        items = data.get("results")
        if not isinstance(items, list):
            return []

        results: list[SearchResult] = []
        seen: set[object] = set()
        for item in items:
            if len(results) >= limit:
                break
            if not isinstance(item, dict):
                continue
            # A dataset is keyed by its identifier, falling back to its slug.
            key = item.get("identifier") or item.get("slug")
            if key is not None:
                if key in seen:
                    continue
                seen.add(key)
            built = self._build_result(item, len(results) + 1)
            if built is None:
                continue
            results.append(built)
        return results

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search catalog.data.gov for datasets matching *query*.

        A blank query performs no request.  The catalog ranks matches by its
        own relevance score, which is preserved in the returned order.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        async with self._client() as client:
            resp = await client.get(
                _SEARCH_URL,
                params={"q": cleaned, "per_page": limit},
            )
            resp.raise_for_status()
            data = resp.json()

        return ProviderResult(results=self._parse(data, limit))
