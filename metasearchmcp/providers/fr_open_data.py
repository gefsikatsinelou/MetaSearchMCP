"""Search France's national open data portal for datasets.

``data.gouv.fr`` is the French Government's national open data portal, built on
the ``udata`` platform (not CKAN).  It publishes dataset metadata from
ministries, public agencies, regions, local authorities and other public bodies,
as well as from open-data aggregators.  Its public, keyless dataset search
endpoint is::

    GET https://www.data.gouv.fr/api/1/datasets/?q=QUERY&page_size=N

The response is ``{"data": [...], "total": <total matches>, "page": 1,
"page_size": N, ...}``.  Every dataset record carries a ``title`` and a
``description`` (often Markdown/HTML), a ``slug`` (a stable identifier used to
build the dataset page URL), its ``keywords``/``tags``, the publishing
``organization`` (with a display ``name`` and ``acronym``), the available
``resources`` (each with a ``format``), the ``license`` code, the ``created_at``
and ``last_update`` timestamps and usage ``metrics``.

This complements the EU (data.europa.eu), U.S. (catalog.data.gov), Australian
(data.gov.au), UK (ckan.publishing.service.gov.uk), Canadian (open.canada.ca),
Irish (data.gov.ie) and Italian (dati.gov.it) open-data providers with a
catalogue of French public-sector datasets.  No API key is required.
"""

from __future__ import annotations

import html
import re
from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://www.data.gouv.fr/api/1/datasets/"
# Human-readable dataset page; the slug identifies the dataset.
_DATASET_PAGE_URL = "https://www.data.gouv.fr/datasets/"
# The API pages its result lists; keep pages small for agents.
_MAX_API_RESULTS = 50
# Characters of the dataset description copied into the snippet.
_SNIPPET_DESCRIPTION_LENGTH = 180
# Tag and distribution-format values listed before closing with an ellipsis.
_SNIPPET_TAG_LIMIT = 5
_SNIPPET_FORMAT_LIMIT = 4

# Matches an HTML/XML tag so it can be stripped from free-text fields.
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _strip_html(value: object) -> str:
    """Return *value* as plain text with HTML tags removed and entities decoded."""
    text = _clean(value)
    if not text:
        return ""
    return _clean(html.unescape(_TAG_RE.sub(" ", text)))


def _string_list(value: object, limit: int | None = None) -> list[str]:
    """Return a deduplicated list of non-empty strings from *value*.

    Only string entries are kept, preserving order and capping the result at
    *limit* items when a limit is given.
    """
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for entry in value:
        label = _clean(entry)
        if label and label not in items:
            items.append(label)
        if limit is not None and len(items) >= limit:
            break
    return items


class FrOpenDataProvider(BaseProvider):
    """Search France's national open data portal for public-sector datasets.

    Keyless.  Queries the data.gouv.fr dataset search endpoint in a single
    request and returns one hit per dataset, carrying the title, description,
    publishing organization, tags, distribution formats, resource count and
    licence, and linking to the dataset page on the French open data portal.
    """

    name = "fr_open_data"
    description = (
        "Search data.gouv.fr — France's national open data portal — for "
        "public-sector datasets from ministries, public agencies, regions, "
        "local authorities and other public bodies (title, description, "
        "organization, tags, distribution formats, resource count, licence) "
        "via the keyless udata search API, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "gov", "data", "knowledge"]

    @staticmethod
    def _organization(item: dict[str, Any]) -> str:
        """Return the publishing organization's display name (with acronym)."""
        organization = item.get("organization")
        if not isinstance(organization, dict):
            return _clean(organization)
        name = _clean(organization.get("name"))
        acronym = _clean(organization.get("acronym"))
        if name and acronym and acronym.lower() != name.lower():
            return f"{name} ({acronym})"
        return name or acronym

    @staticmethod
    def _formats(item: dict[str, Any]) -> list[str]:
        """Return the distinct distribution formats across the dataset resources."""
        resources = item.get("resources")
        if not isinstance(resources, list):
            return []
        formats: list[str] = []
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            fmt = _clean(resource.get("format"))
            if fmt and fmt not in formats:
                formats.append(fmt)
        return formats

    @staticmethod
    def _snippet(
        description: str,
        organization: str,
        tags: list[str],
        formats: list[str],
        num_resources: int,
        license_code: str,
    ) -> str:
        """Compose the snippet for a single dataset."""
        parts: list[str] = []
        if description:
            parts.append(description[:_SNIPPET_DESCRIPTION_LENGTH])
        if organization:
            parts.append(f"Organization: {organization}")
        if tags:
            parts.append(f"Tags: {', '.join(tags)}")
        if formats:
            parts.append(f"Formats: {', '.join(formats)}")
        if num_resources:
            parts.append(f"Resources: {num_resources}")
        if license_code:
            parts.append(f"License: {license_code}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(self, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw data.gouv.fr dataset record."""
        title = _clean(item.get("title"))
        slug = _clean(item.get("slug")) or _clean(item.get("id"))
        if not title or not slug:
            return None

        description = _strip_html(item.get("description"))
        organization = self._organization(item)
        tags = _string_list(item.get("tags"), _SNIPPET_TAG_LIMIT)
        formats = self._formats(item)[:_SNIPPET_FORMAT_LIMIT]
        license_code = _clean(item.get("license"))
        resources = item.get("resources")
        num_resources = len(resources) if isinstance(resources, list) else 0
        created = _clean(item.get("created_at"))
        created_date = created[:10] if created else ""
        modified = _clean(item.get("last_update")) or _clean(item.get("last_modified"))
        updated = modified[:10] if modified else ""
        page = _clean(item.get("page")) or f"{_DATASET_PAGE_URL}{quote(slug, safe='')}"

        return SearchResult(
            title=title,
            url=page,
            snippet=self._snippet(
                description,
                organization,
                tags,
                formats,
                num_resources,
                license_code,
            ),
            source="data.gouv.fr",
            rank=rank,
            provider=self.name,
            published_date=created_date or updated or None,
            extra={
                "id": _clean(item.get("id")) or None,
                "slug": slug,
                "organization": organization or None,
                "tags": tags,
                "formats": formats,
                "resources": num_resources,
                "license": license_code or None,
                "created": created_date or None,
                "updated": updated or None,
            },
        )

    def _parse(self, data: object, limit: int) -> list[SearchResult]:
        """Parse a data.gouv.fr search response, deduplicating by dataset id."""
        if not isinstance(data, dict):
            return []
        items = data.get("data")
        if not isinstance(items, list):
            return []

        results: list[SearchResult] = []
        seen: set[object] = set()
        for item in items:
            if len(results) >= limit:
                break
            if not isinstance(item, dict):
                continue
            # A dataset is keyed by its id, falling back to its slug.
            key = item.get("id") or item.get("slug")
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
        """Search France's open data portal for datasets matching *query*.

        A blank query performs no request.  The catalogue ranks matches by its
        own relevance score, which is preserved in the returned results.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        async with self._client() as client:
            resp = await client.get(
                _SEARCH_URL,
                params={"q": cleaned, "page_size": limit},
            )
            resp.raise_for_status()
            data = resp.json()

        return ProviderResult(results=self._parse(data, limit))
