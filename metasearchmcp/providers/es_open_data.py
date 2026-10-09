"""Search datos.gob.es — Spain's national open data portal.

``datos.gob.es`` is Spain's national open data portal (the ``datos.gob.es``
catalogue), aggregating dataset metadata from the central government, the
autonomous communities, provinces and municipalities.  Its public, keyless
Linked Data API exposes a full-text dataset title search endpoint::

    GET https://datos.gob.es/apidata/catalog/dataset/title/QUERY?_pageSize=N

The response is ``{"result": {"items": [...], "itemsPerPage": N, "page": P,
...}}``.  Every dataset record carries a ``title`` (a list of localised
``{"_value", "_lang"}`` entries), a ``description`` and ``keyword`` list in the
same shape, its canonical ``_about`` page URL, the ``distribution`` list of
resources (each with an ``accessURL`` and a distribution ``format``), the
``publisher`` organization URI, the topical ``theme`` URI, the ``issued`` and
``modified`` timestamps, and the ``identifier``.

This complements the U.S. (catalog.data.gov), European (data.europa.eu),
Australian (data.gov.au), UK (ckan.publishing.service.gov.uk), Canadian
(open.canada.ca), Irish (data.gov.ie), Italian (dati.gov.it), French
(data.gouv.fr), German (www.govdata.de) and Dutch (data.overheid.nl) open-data
providers with a catalogue of Spanish public-sector datasets.  No API key is
required.
"""

from __future__ import annotations

import html
import re
from typing import Any, ClassVar
from urllib.parse import quote, unquote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://datos.gob.es/apidata/catalog/dataset/title/"
# The Linked Data API pages its result lists; keep pages small for agents.
_MAX_API_RESULTS = 50
# Characters of the dataset description copied into the snippet.
_SNIPPET_DESCRIPTION_LENGTH = 180
# Keyword and distribution-format values listed before closing.
_SNIPPET_KEYWORD_LIMIT = 5
_SNIPPET_FORMAT_LIMIT = 4
# Preferred language for localised title/description/keyword values.
_PREFERRED_LANG = "es"

# Matches an HTML/XML tag so it can be stripped from free-text fields.
_TAG_RE = re.compile(r"<[^>]+>")
# Extracts the day, month abbreviation and year from a datos.gob.es date such
# as "lun, 22 dic 2025 15:30:56 GMT+0000".
_DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-zÁÉÍÓÚÜáéíóúü]{3})\s+(\d{4})")

# Spanish month abbreviations as used in datos.gob.es date strings.
_MONTHS = {
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,
}


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
    return unquote(text)


def _iso_date(value: object) -> str | None:
    """Convert a Spanish localised date string to an ISO ``YYYY-MM-DD`` date.

    datos.gob.es renders dates such as ``"lun, 22 dic 2025 15:30:56 GMT+0000"``.
    Returns ``None`` when no recognisable day/month/year triple is present.
    """
    match = _DATE_RE.search(_clean(value))
    if not match:
        return None
    day = int(match.group(1))
    month = _MONTHS.get(match.group(2).lower())
    year = int(match.group(3))
    if month is None or not 1 <= day <= 31:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _localized(value: object, prefer: str = _PREFERRED_LANG) -> str:
    """Return the text of a localised Linked Data API field as a plain string.

    *value* is normally a list of ``{"_value", "_lang"}`` mappings; the entry
    whose ``_lang`` matches *prefer* wins, otherwise the first usable entry is
    used.  A bare string or single mapping is returned directly.
    """
    if isinstance(value, str):
        return _clean(value)
    if isinstance(value, dict):
        return _clean(value.get("_value"))
    if not isinstance(value, list):
        return ""
    fallback = ""
    for entry in value:
        if not isinstance(entry, dict):
            continue
        text = _clean(entry.get("_value"))
        if not text:
            continue
        if not fallback:
            fallback = text
        if _clean(entry.get("_lang")) == prefer:
            return text
    return fallback


def _keyword_labels(value: object, limit: int) -> list[str]:
    """Return deduplicated keyword labels from a localised keyword list."""
    if not isinstance(value, list):
        return []
    labels: list[str] = []
    for entry in value:
        label = _localized(entry)
        if label and label not in labels:
            labels.append(label)
        if len(labels) >= limit:
            break
    return labels


def _formats(distribution: object, limit: int) -> list[str]:
    """Return the distinct distribution formats across a dataset's resources.

    ``distribution`` is normally a list of resource mappings but may be a bare
    mapping when a dataset has a single distribution.
    """
    if isinstance(distribution, dict):
        entries: list[object] = [distribution]
    elif isinstance(distribution, list):
        entries = distribution
    else:
        return []
    formats: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        label = _last_segment(entry.get("format"))
        if label and label not in formats:
            formats.append(label)
        if len(formats) >= limit:
            break
    return formats


def _theme_labels(value: object, limit: int) -> list[str]:
    """Return topical category labels from the ``theme`` URI(s)."""
    if isinstance(value, str):
        entries: list[object] = [value]
    elif isinstance(value, list):
        entries = value
    else:
        return []
    labels: list[str] = []
    for entry in entries:
        label = _last_segment(entry)
        if label and label not in labels:
            labels.append(label)
        if len(labels) >= limit:
            break
    return labels


class EsOpenDataProvider(BaseProvider):
    """Search datos.gob.es — Spain's open data portal — for datasets.

    Keyless.  Queries the portal's dataset title search in a single request and
    returns one hit per dataset, carrying the title, description, keywords,
    topical categories, distribution formats, publisher and timestamps, and
    linking to the canonical dataset page on ``datos.gob.es``.
    """

    name = "es_open_data"
    description = (
        "Search datos.gob.es — Spain's national open data portal — for "
        "public-sector datasets from the central government, the autonomous "
        "communities, provinces and municipalities (title, description, "
        "keywords, topical categories, distribution formats, publisher) via "
        "the keyless Linked Data API, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "gov", "data", "knowledge"]

    @staticmethod
    def _snippet(
        description: str,
        keywords: list[str],
        categories: list[str],
        formats: list[str],
        publisher: str,
    ) -> str:
        """Compose the snippet for a single dataset."""
        parts: list[str] = []
        if description:
            parts.append(description[:_SNIPPET_DESCRIPTION_LENGTH])
        if keywords:
            parts.append(f"Keywords: {', '.join(keywords)}")
        if categories:
            parts.append(f"Categories: {', '.join(categories)}")
        if formats:
            parts.append(f"Formats: {', '.join(formats)}")
        if publisher:
            parts.append(f"Publisher: {publisher}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(self, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw datos.gob.es dataset record."""
        title = _localized(item.get("title"))
        url = _clean(item.get("_about"))
        if not title or not url:
            return None

        description = _strip_html(_localized(item.get("description")))
        keywords = _keyword_labels(item.get("keyword"), _SNIPPET_KEYWORD_LIMIT)
        categories = _theme_labels(item.get("theme"), _SNIPPET_KEYWORD_LIMIT)
        formats = _formats(item.get("distribution"), _SNIPPET_FORMAT_LIMIT)
        publisher = _last_segment(item.get("publisher"))
        published = _iso_date(item.get("issued"))
        updated = _iso_date(item.get("modified"))

        return SearchResult(
            title=title,
            url=url,
            snippet=self._snippet(
                description,
                keywords,
                categories,
                formats,
                publisher,
            ),
            source="datos.gob.es",
            rank=rank,
            provider=self.name,
            published_date=published or updated,
            extra={
                "identifier": _clean(item.get("identifier")) or None,
                "keywords": keywords,
                "categories": categories,
                "formats": formats,
                "publisher": publisher or None,
                "theme": _clean(item.get("theme")) or None,
                "published": published,
                "updated": updated,
            },
        )

    def _parse(self, data: object, limit: int) -> list[SearchResult]:
        """Parse a Linked Data API response, deduplicating by dataset URL."""
        if not isinstance(data, dict):
            return []
        result = data.get("result")
        if not isinstance(result, dict):
            return []
        items = result.get("items")
        if not isinstance(items, list):
            return []

        results: list[SearchResult] = []
        seen: set[object] = set()
        for item in items:
            if len(results) >= limit:
                break
            if not isinstance(item, dict):
                continue
            # A dataset is keyed by its canonical ``_about`` URL, then its id.
            key = item.get("_about") or item.get("identifier")
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
        """Search the Spanish open data portal for datasets matching *query*.

        A blank query performs no request.  The catalogue ranks matches by its
        own relevance score, which is preserved in the returned results.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        url = f"{_SEARCH_URL}{quote(cleaned, safe='')}"

        async with self._client() as client:
            resp = await client.get(url, params={"_pageSize": limit, "_page": 0})
            resp.raise_for_status()
            data = resp.json()

        return ProviderResult(results=self._parse(data, limit))
