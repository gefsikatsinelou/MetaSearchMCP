"""Search the Australian open data portal (data.gov.au) for datasets.

``data.gov.au`` is the Australian Government's public catalogue that harvests
dataset metadata from federal, state and local publishers.  Its CKAN Action
API exposes a public, keyless full-text dataset search endpoint::

    GET https://data.gov.au/data/api/3/action/package_search?q=QUERY&rows=N

The response is ``{"success": true, "result": {"count": <total matches>,
"results": [...]}}``.  Every dataset record carries a ``title`` and ``notes``
description, its ``name`` (a stable slug used to build the dataset page URL),
the harvesting ``organization`` (with its display ``title``), the ``author``,
the subject ``tags``, the available ``resources`` (each with a download
``format``), the ``license_title`` and the ``metadata_modified`` timestamp.

This complements the U.S. (catalog.data.gov) and European (data.europa.eu)
open-data providers with a catalogue of Australian public-sector datasets.
No API key is required.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://data.gov.au/data/api/3/action/package_search"
# Human-readable dataset page; the slug (``name``) identifies the dataset.
_DATASET_PAGE_URL = "https://data.gov.au/dataset/"
# The CKAN Action API pages its result lists; keep pages small for agents.
_MAX_API_RESULTS = 50
# Characters of the dataset description copied into the snippet.
_SNIPPET_DESCRIPTION_LENGTH = 180
# Tag and distribution-format values listed before closing with an ellipsis.
_SNIPPET_TAG_LIMIT = 5
_SNIPPET_FORMAT_LIMIT = 4


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _string_list(value: object) -> list[str]:
    """Return a deduplicated list of non-empty strings from *value*."""
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for entry in value:
        label = _clean(entry)
        if label and label not in items:
            items.append(label)
    return items


class AuOpenDataProvider(BaseProvider):
    """Search the Australian open data portal (data.gov.au) for datasets.

    Keyless.  Queries the data.gov.au CKAN ``package_search`` action in a single
    request and returns one hit per dataset, carrying the title, description,
    harvesting organization, author, tags, distribution formats, resource count
    and licence, and linking to the dataset page on data.gov.au.
    """

    name = "au_open_data"
    description = (
        "Search data.gov.au — the Australian open data portal — for "
        "public-sector datasets from federal, state and local publishers "
        "(title, description, organization, author, tags, distribution "
        "formats, licence) via the keyless CKAN Action API, no API key "
        "required."
    )
    tags: ClassVar[list[str]] = ["web", "gov", "data", "knowledge"]

    @staticmethod
    def _organization(item: dict[str, Any]) -> str:
        """Return the harvesting organization's display title."""
        organization = item.get("organization")
        if isinstance(organization, dict):
            return _clean(organization.get("title")) or _clean(
                organization.get("name"),
            )
        return _clean(organization)

    @staticmethod
    def _tags(item: dict[str, Any]) -> list[str]:
        """Return the dataset's subject tags (CKAN wraps each as a mapping)."""
        raw = item.get("tags")
        if not isinstance(raw, list):
            return []
        names: list[str] = []
        for tag in raw:
            name = ""
            if isinstance(tag, dict):
                name = _clean(tag.get("name"))
            elif isinstance(tag, str):
                name = _clean(tag)
            if name and name not in names:
                names.append(name)
        return names

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
        author: str,
        tags: list[str],
        formats: list[str],
        num_resources: int,
        license_title: str,
    ) -> str:
        """Compose the snippet for a single dataset."""
        parts: list[str] = []
        if description:
            parts.append(description[:_SNIPPET_DESCRIPTION_LENGTH])
        if organization:
            parts.append(f"Organization: {organization}")
        if author:
            parts.append(f"Author: {author}")
        if tags:
            parts.append(f"Tags: {', '.join(tags[:_SNIPPET_TAG_LIMIT])}")
        if formats:
            parts.append(f"Formats: {', '.join(formats[:_SNIPPET_FORMAT_LIMIT])}")
        if num_resources:
            parts.append(f"Resources: {num_resources}")
        if license_title:
            parts.append(f"License: {license_title}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(self, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw CKAN dataset record."""
        title = _clean(item.get("title"))
        slug = _clean(item.get("name"))
        if not title or not slug:
            return None

        description = _clean(item.get("notes"))
        organization = self._organization(item)
        author = _clean(item.get("author"))
        tags = self._tags(item)
        formats = self._formats(item)
        license_title = _clean(item.get("license_title"))
        num_resources = item.get("num_resources")
        num_resources = num_resources if isinstance(num_resources, int) else 0
        modified = _clean(item.get("metadata_modified"))
        updated = modified[:10] if modified else ""

        return SearchResult(
            title=title,
            url=f"{_DATASET_PAGE_URL}{quote(slug, safe='')}",
            snippet=self._snippet(
                description,
                organization,
                author,
                tags,
                formats,
                num_resources,
                license_title,
            ),
            source="data.gov.au",
            rank=rank,
            provider=self.name,
            published_date=updated or None,
            extra={
                "id": _clean(item.get("id")) or None,
                "name": slug,
                "organization": organization or None,
                "author": author or None,
                "tags": tags,
                "formats": formats,
                "resources": num_resources,
                "license": license_title or None,
                "is_open": bool(item.get("isopen")),
                "updated": updated or None,
            },
        )

    def _parse(self, data: object, limit: int) -> list[SearchResult]:
        """Parse a CKAN package_search response, deduplicating by dataset id."""
        if not isinstance(data, dict):
            return []
        result = data.get("result")
        if not isinstance(result, dict):
            return []
        items = result.get("results")
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
            key = item.get("id") or item.get("name")
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
        """Search data.gov.au for datasets matching *query*.

        A blank query performs no request.  The portal ranks matches by its own
        relevance score, which is preserved in the returned results.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        async with self._client() as client:
            resp = await client.get(
                _SEARCH_URL,
                params={"q": cleaned, "rows": limit},
            )
            resp.raise_for_status()
            data = resp.json()

        return ProviderResult(results=self._parse(data, limit))
