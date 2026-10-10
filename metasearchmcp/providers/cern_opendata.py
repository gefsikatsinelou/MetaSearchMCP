"""Search CERN Open Data — CERN's open research data portal.

``opendata.cern.ch`` is CERN's open data portal: the repository where the LHC
experiments (ALICE, ATLAS, CMS, LHCb) and other CERN collaborations publish
research-grade datasets, simulated events, software and documentation for
reuse, education and outreach.  Its public, keyless Invenio REST API exposes a
full-text record search endpoint::

    GET https://opendata.cern.ch/api/records?q=QUERY&size=N&page=P

The response is ``{"hits": {"total": <count>, "hits": [...]}}``.  Every record
carries a ``metadata`` object with the ``title``, an ``abstract`` (a mapping
whose ``description`` holds HTML), the ``authors`` (each with an optional
ORCID), ``keywords``, the ``experiment`` (e.g. ``CMS``), a ``doi``, the
``type`` (``primary`` such as ``Dataset`` plus ``secondary`` facets), the
``date_published`` and ``date_created`` values, the ``distribution`` formats
(``csv``, ``json``, ``ig``, ...), the ``availability`` and ``license``, the
``publisher`` and the ``collections`` the record belongs to.  The stable
``recid`` identifies the human-readable record page.

This complements the other research-data providers (Zenodo, Figshare, Dryad,
Harvard Dataverse, DataCite) with the CERN high-energy-physics data corpus.
No API key is required.
"""

from __future__ import annotations

import html
import re
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://opendata.cern.ch/api/records"
# Human-readable record page; the stable ``recid`` identifies a record.
_RECORD_URL = "https://opendata.cern.ch/record/"
# The Invenio API pages its result lists; keep pages small for agents.
_MAX_API_RESULTS = 50
# Characters of the record abstract copied into the snippet.
_SNIPPET_DESCRIPTION_LENGTH = 180
# Author, keyword, experiment, collection and distribution-format values listed
# before the snippet closes.
_SNIPPET_AUTHOR_LIMIT = 3
_SNIPPET_KEYWORD_LIMIT = 5
_SNIPPET_EXPERIMENT_LIMIT = 3
_SNIPPET_COLLECTION_LIMIT = 2
_SNIPPET_FORMAT_LIMIT = 4
# Creation years recorded before the list closes.
_SNIPPET_CREATED_LIMIT = 4

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


def _text(value: object) -> str:
    """Return a single plain-text string from a scalar, mapping or list field.

    Invenio record fields are sometimes plain strings, sometimes a mapping with
    a ``title``/``value`` key, and sometimes a list of such entries; the first
    usable value is returned.
    """
    if isinstance(value, str):
        return _clean(value)
    if isinstance(value, dict):
        return _clean(value.get("title")) or _clean(value.get("value"))
    if isinstance(value, list):
        for entry in value:
            text = _text(entry)
            if text:
                return text
    return ""


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


def _authors(value: object, limit: int) -> list[str]:
    """Return author names from a list of ``{"name", "orcid"}`` mappings."""
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for entry in value:
        if isinstance(entry, dict):
            name = _clean(entry.get("name"))
        else:
            name = _clean(entry)
        if name and name not in names:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def _abstract(item: dict[str, Any]) -> str:
    """Return the record abstract as plain text, stripping its HTML markup."""
    value = item.get("abstract")
    if isinstance(value, dict):
        return _strip_html(value.get("description"))
    return _strip_html(value)


def _formats(value: object, limit: int) -> list[str]:
    """Return distribution formats from the ``distribution`` mapping."""
    if not isinstance(value, dict):
        return []
    return _string_list(value.get("formats"), limit)


def _type_label(value: object) -> str:
    """Return the primary record type (e.g. ``Dataset``)."""
    if isinstance(value, dict):
        return _clean(value.get("primary"))
    return _clean(value)


def _type_facets(value: object, limit: int) -> list[str]:
    """Return the secondary record-type facets (e.g. ``Derived``)."""
    if not isinstance(value, dict):
        return []
    return _string_list(value.get("secondary"), limit)


def _license(value: object) -> str:
    """Return a short licence label from a licence mapping or plain string."""
    if isinstance(value, dict):
        return _clean(value.get("attribution")) or _clean(value.get("name"))
    return _clean(value)


def _date(value: object) -> str | None:
    """Return a ``YYYY``-or-``YYYY-MM-DD`` date prefix, or None when absent."""
    text = _text(value)
    return text[:10] if text else None


class CernOpenDataProvider(BaseProvider):
    """Search CERN Open Data — CERN's open research data portal — for records.

    Keyless.  Queries the portal's Invenio record search in a single request and
    returns one hit per record, carrying the title, abstract, authors, keywords,
    experiment, DOI, record type, publication date, distribution formats,
    availability, licence and publisher, and linking to the record page on
    ``opendata.cern.ch``.
    """

    name = "cern_opendata"
    description = (
        "Search CERN Open Data (opendata.cern.ch) — CERN's open research data "
        "portal — for research datasets, simulated events, software and "
        "documentation published by the LHC experiments (ALICE, ATLAS, CMS, "
        "LHCb) and other CERN collaborations (title, abstract, authors, "
        "keywords, experiment, DOI, record type, publication date, "
        "distribution formats, availability, licence, publisher) via the "
        "keyless Invenio API, no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "data", "science", "physics"]

    @staticmethod
    def _snippet(
        description: str,
        authors: list[str],
        keywords: list[str],
        experiments: list[str],
        collections: list[str],
        type_label: str,
        formats: list[str],
        availability: str,
        license_label: str,
    ) -> str:
        """Compose the snippet for a single record."""
        parts: list[str] = []
        if description:
            parts.append(description[:_SNIPPET_DESCRIPTION_LENGTH])
        if authors:
            parts.append(f"Authors: {', '.join(authors)}")
        if keywords:
            parts.append(f"Keywords: {', '.join(keywords)}")
        if experiments:
            parts.append(f"Experiment: {', '.join(experiments)}")
        if collections:
            parts.append(f"Collections: {', '.join(collections)}")
        if type_label:
            parts.append(f"Type: {type_label}")
        if formats:
            parts.append(f"Formats: {', '.join(formats)}")
        if availability:
            parts.append(f"Availability: {availability}")
        if license_label:
            parts.append(f"License: {license_label}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        record_id: object,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw CERN Open Data record."""
        title = _text(item.get("title"))
        recid = _clean(item.get("recid")) or _clean(record_id)
        if not title or not recid:
            return None

        description = _abstract(item)
        authors = _authors(item.get("authors"), _SNIPPET_AUTHOR_LIMIT)
        keywords = _string_list(item.get("keywords"), _SNIPPET_KEYWORD_LIMIT)
        experiments = _string_list(item.get("experiment"), _SNIPPET_EXPERIMENT_LIMIT)
        collections = _string_list(
            item.get("collections"),
            _SNIPPET_COLLECTION_LIMIT,
        )
        formats = _formats(item.get("distribution"), _SNIPPET_FORMAT_LIMIT)
        type_label = _type_label(item.get("type"))
        type_facets = _type_facets(item.get("type"), _SNIPPET_KEYWORD_LIMIT)
        license_label = _license(item.get("license"))
        availability = _clean(item.get("availability"))
        publisher = _clean(item.get("publisher"))
        doi = _clean(item.get("doi"))
        published = _date(item.get("date_published"))
        created = _string_list(item.get("date_created"), _SNIPPET_CREATED_LIMIT)

        return SearchResult(
            title=title,
            url=f"{_RECORD_URL}{recid}",
            snippet=self._snippet(
                description,
                authors,
                keywords,
                experiments,
                collections,
                type_label,
                formats,
                availability,
                license_label,
            ),
            source="opendata.cern.ch",
            rank=rank,
            provider=self.name,
            published_date=published,
            extra={
                "recid": recid,
                "doi": doi or None,
                "type": type_label or None,
                "type_facets": type_facets,
                "authors": authors,
                "keywords": keywords,
                "experiment": experiments,
                "collections": _string_list(
                    item.get("collections"),
                    _SNIPPET_KEYWORD_LIMIT,
                ),
                "formats": formats,
                "availability": availability or None,
                "license": license_label or None,
                "publisher": publisher or None,
                "published": published,
                "created": created,
            },
        )

    def _parse(self, data: object, limit: int) -> list[SearchResult]:
        """Parse an Invenio search response, deduplicating by record id."""
        if not isinstance(data, dict):
            return []
        hits = data.get("hits")
        if not isinstance(hits, dict):
            return []
        records = hits.get("hits")
        if not isinstance(records, list):
            return []

        results: list[SearchResult] = []
        seen: set[object] = set()
        for record in records:
            if len(results) >= limit:
                break
            if not isinstance(record, dict):
                continue
            metadata = record.get("metadata")
            if not isinstance(metadata, dict):
                continue
            # A record is keyed by its stable recid, falling back to its id.
            key = metadata.get("recid") or record.get("id")
            if key is not None:
                if key in seen:
                    continue
                seen.add(key)
            built = self._build_result(metadata, record.get("id"), len(results) + 1)
            if built is None:
                continue
            results.append(built)
        return results

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the CERN Open Data portal for records matching *query*.

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
                params={"q": cleaned, "size": limit, "page": 1},
            )
            resp.raise_for_status()
            data = resp.json()

        return ProviderResult(results=self._parse(data, limit))
