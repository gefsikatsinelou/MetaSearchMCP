"""Search GovData — the German open data portal — for public datasets.

``www.govdata.de`` is Germany's national open data portal (GovData), the CKAN
instance that harvests dataset metadata from the federal government, the
Bundesländer, municipalities and other public bodies.  Its CKAN Action API
exposes a public, keyless full-text dataset search endpoint::

    GET https://ckan.govdata.de/api/3/action/package_search?q=QUERY&rows=N

The response is ``{"success": true, "result": {"count": <total matches>,
"results": [...]}}``.  Every dataset record carries a ``title`` and ``notes``
description, its ``name`` (a stable slug used to build the dataset page URL),
the harvesting ``organization`` (with its display ``title``), the ``author``,
the ``tags`` and ``groups`` (topical categories such as "Umwelt"), the
available ``resources`` (each with a distribution ``format``), the
``license_title``, the ``isopen`` flag, the resource count and the
``metadata_modified`` timestamp.  Publication metadata is also mirrored in the
``extras`` list (``publisher_name``, ``theme``, ``issued``, ``modified``).

This complements the U.S. (catalog.data.gov), European (data.europa.eu),
Australian (data.gov.au), UK (ckan.publishing.service.gov.uk), Canadian
(open.canada.ca), Irish (data.gov.ie), Italian (dati.gov.it) and French
(data.gouv.fr) open-data providers with a catalogue of German public-sector
datasets.  No API key is required.
"""

from __future__ import annotations

import html
import re
from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://ckan.govdata.de/api/3/action/package_search"
# Human-readable dataset page; the slug (``name``) identifies the dataset.
_DATASET_PAGE_URL = "https://www.govdata.de/suche/daten/"
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


def _format_label(value: object) -> str:
    """Return a short distribution-format label.

    GovData stores distribution formats either as plain strings or as EU
    authority URIs (e.g. ``.../file-type/CSV``); the last path segment is used
    for the latter so the label stays readable.
    """
    text = _clean(value)
    if not text:
        return ""
    if "/" in text:
        text = text.rstrip("/").rsplit("/", 1)[-1]
    return text


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


def _extras_map(item: dict[str, Any]) -> dict[str, str]:
    """Return the dataset's ``extras`` list as a plain ``{key: value}`` mapping."""
    extras = item.get("extras")
    if not isinstance(extras, list):
        return {}
    mapping: dict[str, str] = {}
    for entry in extras:
        if not isinstance(entry, dict):
            continue
        key = _clean(entry.get("key"))
        if key:
            mapping[key] = _clean(entry.get("value"))
    return mapping


class GovDataDeProvider(BaseProvider):
    """Search GovData — the German open data portal — for public datasets.

    Keyless.  Queries the GovData ``package_search`` action in a single request
    and returns one hit per dataset, carrying the title, description,
    harvesting organization, publisher, tags, topical categories, distribution
    formats, resource count and licence, and linking to the dataset page on the
    German open data portal.
    """

    name = "govdata_de"
    description = (
        "Search GovData (www.govdata.de) — Germany's national open data portal "
        "— for public-sector datasets harvested from the federal government, "
        "the Bundesländer, municipalities and other public bodies (title, "
        "description, organization, publisher, tags, categories, distribution "
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
    def _snippet(
        description: str,
        organization: str,
        publisher: str,
        author: str,
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
        if author:
            parts.append(f"Author: {author}")
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
        extras = _extras_map(item)
        publisher = extras.get("publisher_name", "")
        author = _clean(item.get("author")) or _clean(item.get("maintainer"))
        tags_found = _labels(item.get("tags"), _SNIPPET_TAG_LIMIT, "name")
        categories = _labels(item.get("groups"), _SNIPPET_CATEGORY_LIMIT, "title")
        formats = _formats(item.get("resources"), _SNIPPET_FORMAT_LIMIT)
        license_title = _clean(item.get("license_title"))
        num_resources = item.get("num_resources")
        num_resources = num_resources if isinstance(num_resources, int) else 0
        modified = _clean(item.get("metadata_modified")) or extras.get("modified", "")
        updated = modified[:10] if modified else ""
        issued = extras.get("issued", "") or _clean(item.get("metadata_created"))
        published_date = issued[:10] if issued else ""

        return SearchResult(
            title=title,
            url=f"{_DATASET_PAGE_URL}{quote(slug, safe='')}",
            snippet=self._snippet(
                description,
                organization,
                publisher,
                author,
                tags_found,
                categories,
                formats,
                num_resources,
                license_title,
            ),
            source="www.govdata.de",
            rank=rank,
            provider=self.name,
            published_date=published_date or updated or None,
            extra={
                "id": _clean(item.get("id")) or None,
                "name": slug,
                "organization": organization or None,
                "publisher": publisher or None,
                "author": author or None,
                "tags": tags_found,
                "categories": categories,
                "formats": formats,
                "resources": num_resources,
                "license": license_title or None,
                "is_open": bool(item.get("isopen")),
                "theme": extras.get("theme") or None,
                "harvested_portal": extras.get("metadata_harvested_portal") or None,
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
        """Search the German open data portal for datasets matching *query*.

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
