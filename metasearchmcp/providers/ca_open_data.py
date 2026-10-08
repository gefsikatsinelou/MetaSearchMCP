"""Search the Government of Canada open data portal for datasets.

``open.canada.ca/data`` is the Government of Canada's open data portal, the
CKAN instance behind open.canada.ca.  It harvests dataset metadata from federal
departments and agencies as well as provincial, territorial and municipal
publishers.  Its CKAN Action API exposes a public, keyless full-text dataset
search endpoint::

    GET https://open.canada.ca/data/api/3/action/package_search?q=QUERY&rows=N

The response is ``{"success": true, "result": {"count": <total matches>,
"results": [...]}}``.  Every dataset record carries a ``title`` and ``notes``
description, its ``name`` (a stable slug used to build the dataset page URL),
the harvesting ``organization`` (with its display ``title``), the ``author``,
the bilingual ``keywords`` and ``subject`` lists, the available ``resources``
(each with a download ``format``), the ``license_title``, the ``jurisdiction``
and the ``metadata_modified`` timestamp.

This complements the U.S. (catalog.data.gov), European (data.europa.eu),
Australian (data.gov.au) and UK (ckan.publishing.service.gov.uk) open-data
providers with a catalogue of Canadian public-sector datasets.  No API key is
required.
"""

from __future__ import annotations

import html
import re
from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://open.canada.ca/data/api/3/action/package_search"
# Human-readable dataset page; the slug (``name``) identifies the dataset.
_DATASET_PAGE_URL = "https://open.canada.ca/data/en/dataset/"
# The CKAN Action API pages its result lists; keep pages small for agents.
_MAX_API_RESULTS = 50
# Characters of the dataset description copied into the snippet.
_SNIPPET_DESCRIPTION_LENGTH = 180
# Keyword, subject and distribution-format values listed before closing.
_SNIPPET_KEYWORD_LIMIT = 5
_SNIPPET_SUBJECT_LIMIT = 3
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


def _english(value: object) -> object:
    """Return the English member of a bilingual (``{"en": ..., "fr": ...}``) value.

    Non-mapping values are returned unchanged so callers can treat the result
    as a plain field.
    """
    if isinstance(value, dict):
        return value.get("en") or value.get("fr")
    return value


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


class CaOpenDataProvider(BaseProvider):
    """Search the Government of Canada open data portal for public datasets.

    Keyless.  Queries the open.canada.ca ``package_search`` action in a single
    request and returns one hit per dataset, carrying the title, description,
    harvesting organization, author, keywords, subjects, distribution formats,
    resource count and licence, and linking to the dataset page on the Canadian
    open data portal.
    """

    name = "ca_open_data"
    description = (
        "Search open.canada.ca — the Government of Canada open data portal — "
        "for public-sector datasets from federal, provincial, territorial and "
        "municipal publishers (title, description, organization, author, "
        "keywords, subjects, distribution formats, licence) via the keyless "
        "CKAN Action API, no API key required."
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
    def _keywords(item: dict[str, Any]) -> list[str]:
        """Return the dataset's English keyword list (bilingual dict)."""
        return _string_list(
            _english(item.get("keywords")),
            _SNIPPET_KEYWORD_LIMIT,
        )

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
        keywords: list[str],
        subjects: list[str],
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
        if keywords:
            parts.append(f"Keywords: {', '.join(keywords)}")
        if subjects:
            parts.append(f"Subjects: {', '.join(subjects)}")
        if formats:
            parts.append(f"Formats: {', '.join(formats)}")
        if num_resources:
            parts.append(f"Resources: {num_resources}")
        if license_title:
            parts.append(f"License: {license_title}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(self, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw CKAN dataset record."""
        title = _clean(item.get("title")) or _clean(
            _english(item.get("title_translated")),
        )
        slug = _clean(item.get("name")) or _clean(item.get("id"))
        if not title or not slug:
            return None

        description = _strip_html(item.get("notes")) or _strip_html(
            _english(item.get("notes_translated")),
        )
        organization = self._organization(item)
        author = _clean(item.get("author"))
        keywords = self._keywords(item)
        subjects = _string_list(item.get("subject"), _SNIPPET_SUBJECT_LIMIT)
        formats = self._formats(item)
        license_title = _clean(item.get("license_title"))
        jurisdiction = _clean(item.get("jurisdiction"))
        num_resources = item.get("num_resources")
        num_resources = num_resources if isinstance(num_resources, int) else 0
        modified = _clean(item.get("metadata_modified"))
        updated = modified[:10] if modified else ""
        published = _clean(item.get("date_published"))
        published_date = published[:10] if published else ""

        return SearchResult(
            title=title,
            url=f"{_DATASET_PAGE_URL}{quote(slug, safe='')}",
            snippet=self._snippet(
                description,
                organization,
                author,
                keywords,
                subjects,
                formats,
                num_resources,
                license_title,
            ),
            source="open.canada.ca",
            rank=rank,
            provider=self.name,
            published_date=published_date or updated or None,
            extra={
                "id": _clean(item.get("id")) or None,
                "name": slug,
                "organization": organization or None,
                "author": author or None,
                "keywords": keywords,
                "subjects": subjects,
                "formats": formats,
                "resources": num_resources,
                "license": license_title or None,
                "is_open": bool(item.get("isopen")),
                "jurisdiction": jurisdiction or None,
                "landing_page": _clean(_english(item.get("url"))) or None,
                "published": published_date or None,
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
        """Search the Canadian open data portal for datasets matching *query*.

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
                params={"q": cleaned, "rows": limit},
            )
            resp.raise_for_status()
            data = resp.json()

        return ProviderResult(results=self._parse(data, limit))
