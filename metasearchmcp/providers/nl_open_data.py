"""Search data.overheid.nl — the Dutch national open data portal.

``data.overheid.nl`` is the Netherlands' national open data portal: the CKAN
instance that harvests dataset metadata from central government, provinces,
municipalities, water authorities and other public bodies.  Its CKAN Action
API exposes a public, keyless full-text dataset search endpoint::

    GET https://data.overheid.nl/data/api/3/action/package_search?q=QUERY&rows=N

The response is ``{"success": true, "result": {"count": <total matches>,
"results": [...]}}``.  Every dataset record carries a ``title`` and ``notes``
description, its ``name`` (a stable slug used to build the dataset page URL),
the harvesting ``organization`` (with its display ``title``), the ``publisher``
and ``authority`` (usually OWMS authority URIs naming the responsible body),
the ``tags`` and ``theme`` (topical categories expressed as OWMS URIs), the
available ``resources`` (each with a distribution ``format``), the
``license_title``, the ``isopen`` flag, the resource count and the
``metadata_modified`` timestamp.  Publication metadata is also mirrored in
fields such as ``language``, ``frequency``, ``dataset_status``,
``access_rights`` and ``source_catalog``.

This complements the U.S. (catalog.data.gov), European (data.europa.eu),
Australian (data.gov.au), UK (ckan.publishing.service.gov.uk), Canadian
(open.canada.ca), Irish (data.gov.ie), Italian (dati.gov.it), French
(data.gouv.fr) and German (www.govdata.de) open-data providers with a
catalogue of Dutch public-sector datasets.  No API key is required.
"""

from __future__ import annotations

import html
import re
from typing import Any, ClassVar
from urllib.parse import quote, unquote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://data.overheid.nl/data/api/3/action/package_search"
# Human-readable dataset page; the slug (``name``) identifies the dataset.
_DATASET_PAGE_URL = "https://data.overheid.nl/dataset/"
# The CKAN Action API pages its result lists; keep pages small for agents.
_MAX_API_RESULTS = 50
# Characters of the dataset description copied into the snippet.
_SNIPPET_DESCRIPTION_LENGTH = 180
# Tag, category and distribution-format values listed before closing.
_SNIPPET_TAG_LIMIT = 5
_SNIPPET_CATEGORY_LIMIT = 3
_SNIPPET_FORMAT_LIMIT = 4

# Matches an HTML/XML tag so it can be stripped from free-text fields.
_TAG_RE = re.compile(r"<[^>]+>")
# Trailing parenthetical qualifier on OWMS term URIs, e.g. "(gemeente)".
_QUALIFIER_RE = re.compile(r"\s*\([^)]*\)\s*$")


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


def _last_segment(value: object) -> str:
    """Return the final path segment of a URI, or *value* unchanged if not a URI."""
    text = _clean(value)
    if not text:
        return ""
    if "/" in text:
        text = text.rstrip("/").rsplit("/", 1)[-1]
    return text


def _format_label(value: object) -> str:
    """Return a short distribution-format label from a format string or URI."""
    return _last_segment(value)


def _term_label(value: object) -> str:
    """Return a human-readable label from an OWMS term URI or plain string.

    OWMS terms look like ``.../terms/Groningen_(gemeente)`` or
    ``.../terms/Natuur_en_milieu``; the last path segment is decoded and the
    trailing parenthetical qualifier and underscores are stripped so the label
    reads naturally (e.g. ``Groningen``, ``Natuur en milieu``).
    """
    text = _last_segment(value)
    if not text:
        return ""
    text = _clean(unquote(text).replace("_", " "))
    return _clean(_QUALIFIER_RE.sub("", text))


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


def _labels(value: object, limit: int, key: str) -> list[str]:
    """Return labels from a list of CKAN dict records (e.g. tags or groups).

    Each record is expected to be a mapping; the requested *key* is used, with
    ``display_name``/``title`` preferred over the raw ``name`` where present so
    the labels read naturally.
    """
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        label = (
            _clean(entry.get(key))
            or _clean(entry.get("display_name"))
            or _clean(entry.get("title"))
        )
        if label and label not in items:
            items.append(label)
        if len(items) >= limit:
            break
    return items


def _term_labels(value: object, limit: int) -> list[str]:
    """Return human-readable labels from a list of OWMS term URIs."""
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            continue
        label = _term_label(entry)
        if label and label not in items:
            items.append(label)
        if len(items) >= limit:
            break
    return items


def _formats(resources: object, limit: int) -> list[str]:
    """Return the distinct distribution formats across a dataset's resources."""
    if not isinstance(resources, list):
        return []
    formats: list[str] = []
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        label = _format_label(resource.get("format"))
        if label and label not in formats:
            formats.append(label)
        if len(formats) >= limit:
            break
    return formats


class NlOpenDataProvider(BaseProvider):
    """Search data.overheid.nl — the Dutch open data portal — for datasets.

    Keyless.  Queries the Netherlands' ``package_search`` action in a single
    request and returns one hit per dataset, carrying the title, description,
    harvesting organization, publisher/authority, tags, topical categories
    (themes), distribution formats, resource count and licence, and linking to
    the dataset page on the Dutch open data portal.
    """

    name = "nl_open_data"
    description = (
        "Search data.overheid.nl — the Netherlands' national open data portal "
        "— for public-sector datasets harvested from central government, "
        "provinces, municipalities, water authorities and other public bodies "
        "(title, description, organization, publisher, authority, tags, "
        "categories, distribution formats, resource count, licence) via the "
        "keyless CKAN Action API, no API key required."
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
    def _categories(item: dict[str, Any]) -> list[str]:
        """Return topical categories merged from ``groups`` and ``theme``.

        The Dutch portal usually leaves ``groups`` empty and records subjects as
        OWMS ``theme`` URIs, so the two sources are combined into one
        deduplicated, capped label list.
        """
        categories = _labels(item.get("groups"), _SNIPPET_CATEGORY_LIMIT, "title")
        for label in _term_labels(item.get("theme"), _SNIPPET_CATEGORY_LIMIT):
            if label and label not in categories:
                categories.append(label)
            if len(categories) >= _SNIPPET_CATEGORY_LIMIT:
                break
        return categories[:_SNIPPET_CATEGORY_LIMIT]

    @staticmethod
    def _snippet(
        description: str,
        organization: str,
        publisher: str,
        authority: str,
        tags: list[str],
        categories: list[str],
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
        if publisher:
            parts.append(f"Publisher: {publisher}")
        if authority:
            parts.append(f"Authority: {authority}")
        if tags:
            parts.append(f"Tags: {', '.join(tags)}")
        if categories:
            parts.append(f"Categories: {', '.join(categories)}")
        if formats:
            parts.append(f"Formats: {', '.join(formats)}")
        if num_resources:
            parts.append(f"Resources: {num_resources}")
        if license_title:
            parts.append(f"License: {license_title}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(self, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw CKAN dataset record."""
        title = _clean(item.get("title"))
        slug = _clean(item.get("name")) or _clean(item.get("id"))
        if not title or not slug:
            return None

        description = _strip_html(item.get("notes"))
        organization = self._organization(item)
        publisher = _term_label(item.get("publisher"))
        authority = _term_label(item.get("authority"))
        author = _clean(item.get("author")) or _clean(item.get("maintainer"))
        tags_found = _labels(item.get("tags"), _SNIPPET_TAG_LIMIT, "name")
        categories = self._categories(item)
        formats = _formats(item.get("resources"), _SNIPPET_FORMAT_LIMIT)
        license_title = _clean(item.get("license_title"))
        num_resources = item.get("num_resources")
        num_resources = num_resources if isinstance(num_resources, int) else 0
        modified = _clean(item.get("metadata_modified")) or _clean(
            item.get("modified"),
        )
        updated = modified[:10] if modified else ""
        issued = _clean(item.get("metadata_created"))
        published_date = issued[:10] if issued else ""

        return SearchResult(
            title=title,
            url=f"{_DATASET_PAGE_URL}{quote(slug, safe='')}",
            snippet=self._snippet(
                description,
                organization,
                publisher,
                authority,
                tags_found,
                categories,
                formats,
                num_resources,
                license_title,
            ),
            source="data.overheid.nl",
            rank=rank,
            provider=self.name,
            published_date=published_date or updated or None,
            extra={
                "id": _clean(item.get("id")) or None,
                "name": slug,
                "organization": organization or None,
                "publisher": publisher or None,
                "authority": authority or None,
                "author": author or None,
                "tags": tags_found,
                "categories": categories,
                "formats": formats,
                "resources": num_resources,
                "license": license_title or None,
                "is_open": bool(item.get("isopen")),
                "language": _term_labels(item.get("language"), 1),
                "frequency": _term_label(item.get("frequency")) or None,
                "dataset_status": _term_label(item.get("dataset_status")) or None,
                "access_rights": _term_label(item.get("access_rights")) or None,
                "source_catalog": _clean(item.get("source_catalog")) or None,
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
        """Search the Dutch open data portal for datasets matching *query*.

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
