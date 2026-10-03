"""Search ERIC — the Education Resources Information Center — for research.

``eric.ed.gov`` is the U.S. Institute of Education Sciences' bibliographic
database of education research and information, indexing more than two million
journal articles, reports, conference papers and other education-related
materials.  It exposes a public, keyless search API::

    GET https://api.ies.ed.gov/eric/?search=QUERY&format=json&rows=N

The response is ``{"response": {"numFound": N, "start": 0, "docs": [...]}}``.
Every record carries its accession ``id`` (``EJ…`` for journal articles,
``ED…`` for documents/ERIC reports), ``title``, ``author`` list, journal
``source``, ``description`` (abstract), ``subject`` descriptors,
``publicationtype``, ``publicationdateyear``, ``peerreviewed`` flag, education
``level``, ``issn``/``isbn`` identifiers and a publisher ``url``.

This complements the other scholarly providers with a catalogue focused on
education research and practice.  Free-text values are HTML-escaped by the
API, so they are unescaped before use.  No API key is required.
"""

from __future__ import annotations

import html
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.ies.ed.gov/eric/"
# Canonical record page on eric.ed.gov, keyed by the accession id.
_RECORD_PAGE_URL = "https://eric.ed.gov/?id="
# ERIC paginates its result lists; keep pages modest for agents.
_MAX_API_RESULTS = 200
# Characters of the abstract copied into the snippet.
_SNIPPET_ABSTRACT_LENGTH = 240
# Subject, publication-type and education-level values listed in the snippet.
_SNIPPET_SUBJECT_LIMIT = 5
_SNIPPET_TYPE_LIMIT = 3
_SNIPPET_EDUCATION_LIMIT = 3
# Only the record fields the provider actually consumes are requested.
_FIELDS = ",".join(
    [
        "id",
        "title",
        "author",
        "source",
        "description",
        "subject",
        "publicationtype",
        "publicationdateyear",
        "peerreviewed",
        "educationlevel",
        "issn",
        "publisher",
        "url",
        "language",
    ]
)


def _clean(value: object) -> str:
    """Collapse whitespace and unescape HTML entities in a free-text field."""
    if not value:
        return ""
    return " ".join(html.unescape(str(value)).split())


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


class EricProvider(BaseProvider):
    """Search education research indexed by ERIC (eric.ed.gov).

    Keyless.  Queries the ERIC search API in a single request and returns one
    hit per record, carrying the title, authors, journal or publisher source,
    abstract, subject descriptors, publication type, publication year,
    peer-review status and education level, and linking to the record page on
    eric.ed.gov.
    """

    name = "eric"
    description = (
        "Search ERIC — the Education Resources Information Center — for "
        "education research: journal articles, reports and conference papers "
        "(title, authors, journal/source, abstract, subject descriptors, "
        "publication type and year, peer-review status, education level) via "
        "the keyless ERIC search API, no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "education", "web"]

    @staticmethod
    def _year(item: dict[str, Any]) -> str:
        """Return the publication year as a four-digit string, if present."""
        raw = item.get("publicationdateyear")
        if raw is None:
            return ""
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        year = _clean(raw)
        return year[:4] if year else ""

    @staticmethod
    def _peer_reviewed(item: dict[str, Any]) -> bool:
        """Return whether the record is marked as peer reviewed."""
        raw = item.get("peerreviewed")
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().upper() == "T"

    @staticmethod
    def _snippet(
        abstract: str,
        source: str,
        publication_types: list[str],
        subjects: list[str],
        education_levels: list[str],
        peer_reviewed: bool,
    ) -> str:
        """Compose the snippet for a single ERIC record."""
        parts: list[str] = []
        if abstract:
            parts.append(abstract[:_SNIPPET_ABSTRACT_LENGTH])
        if source:
            parts.append(f"Source: {source}")
        if publication_types:
            parts.append(f"Type: {', '.join(publication_types)}")
        if subjects:
            parts.append(f"Subjects: {', '.join(subjects)}")
        if education_levels:
            parts.append(f"Education level: {', '.join(education_levels)}")
        if peer_reviewed:
            parts.append("Peer reviewed")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw ERIC record."""
        record_id = _clean(item.get("id"))
        title = _clean(item.get("title"))
        if not record_id or not title:
            return None

        authors = _string_list(item.get("author"), 10)
        source = _clean(item.get("source"))
        abstract = _clean(item.get("description"))
        subjects = _string_list(item.get("subject"), _SNIPPET_SUBJECT_LIMIT)
        publication_types = _string_list(
            item.get("publicationtype"),
            _SNIPPET_TYPE_LIMIT,
        )
        education_levels = _string_list(
            item.get("educationlevel"),
            _SNIPPET_EDUCATION_LIMIT,
        )
        peer_reviewed = self._peer_reviewed(item)
        year = self._year(item)
        publisher_url = _clean(item.get("url"))
        issn = ", ".join(_string_list(item.get("issn"), 5))
        language = _string_list(item.get("language"), 3)

        return SearchResult(
            title=title,
            url=f"{_RECORD_PAGE_URL}{record_id}",
            snippet=self._snippet(
                abstract,
                source,
                publication_types,
                subjects,
                education_levels,
                peer_reviewed,
            ),
            source="eric.ed.gov",
            rank=rank,
            provider=self.name,
            published_date=year or None,
            extra={
                "id": record_id,
                "authors": authors,
                "journal": source or None,
                "publication_types": publication_types,
                "subjects": subjects,
                "education_levels": education_levels,
                "peer_reviewed": peer_reviewed,
                "issn": issn or None,
                "language": language,
                "publisher_url": publisher_url or None,
            },
        )

    def _parse(self, data: object, limit: int) -> list[SearchResult]:
        """Parse an ERIC search response, deduplicating hits by accession id."""
        if not isinstance(data, dict):
            return []
        response = data.get("response")
        if not isinstance(response, dict):
            return []
        docs = response.get("docs")
        if not isinstance(docs, list):
            return []

        results: list[SearchResult] = []
        seen: set[str] = set()
        for item in docs:
            if len(results) >= limit:
                break
            if not isinstance(item, dict):
                continue
            record_id = _clean(item.get("id"))
            if record_id:
                if record_id in seen:
                    continue
                seen.add(record_id)
            built = self._build_result(item, len(results) + 1)
            if built is None:
                continue
            results.append(built)
        return results

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search ERIC for records matching *query*.

        A blank query performs no request.  ERIC ranks matches by its own
        relevance score, which is preserved in the returned order.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={
                    "search": cleaned,
                    "format": "json",
                    "rows": limit,
                    "fields": _FIELDS,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return ProviderResult(results=self._parse(data, limit))
