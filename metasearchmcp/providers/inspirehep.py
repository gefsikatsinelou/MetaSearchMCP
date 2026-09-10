"""INSPIRE-HEP literature search via the public, keyless REST API.

INSPIRE-HEP (inspirehep.net, run by CERN and partners) is the reference
database for high-energy physics, indexing well over a million papers,
preprints, conference proceedings, theses, and their citation graphs.  Its
public API requires no API key for anonymous read access:

``GET https://inspirehep.net/api/literature?q=QUERY&size=N&sort=mostrecent``

The ``q`` parameter accepts INSPIRE's rich search syntax (plain free text as
well as fielded terms such as ``a Einstein`` or ``t Higgs``).  Each hit
carries the title, authors, abstract, journal reference, arXiv identifier and
categories, DOI, document type, earliest date, and citation count, plus a link
to the record on inspirehep.net.  Parsing uses only the shared httpx client
from the base provider.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://inspirehep.net/api/literature"
# INSPIRE caps a single listing request at this many items.
_MAX_API_RESULTS = 50
# Restrict the (otherwise very large) payload to just the fields we render.
_FIELDS = (
    "titles,authors,abstracts,arxiv_eprints,publication_info,"
    "dois,citation_count,earliest_date,document_type"
)


def _clean(value: object) -> str:
    """Collapse whitespace and control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


class InspireHEPProvider(BaseProvider):
    """Search high-energy physics literature indexed by INSPIRE-HEP.

    Keyless.  Covers articles, preprints, proceedings, and theses with
    authors, abstracts, journal references, arXiv ids, DOIs, and citation
    counts, plus a link to the record on inspirehep.net.
    """

    name = "inspirehep"
    description = (
        "Search high-energy physics literature (papers, preprints, citations, "
        "authors) via the INSPIRE-HEP API, no key required."
    )
    tags: ClassVar[list[str]] = ["academic", "web", "science", "physics"]

    @staticmethod
    def _record_id(hit: dict[str, Any]) -> str:
        """Return the INSPIRE record id as a string, if present."""
        record_id = hit.get("id")
        return str(record_id) if record_id not in (None, "") else ""

    @staticmethod
    def _title(metadata: dict[str, Any]) -> str:
        """Return the first non-empty title from the record's title list."""
        titles = metadata.get("titles")
        if not isinstance(titles, list):
            return ""
        for entry in titles:
            if isinstance(entry, dict):
                title = _clean(entry.get("title"))
                if title:
                    return title
        return ""

    @staticmethod
    def _authors(metadata: dict[str, Any]) -> list[str]:
        """Extract author names from the record's author list."""
        authors = metadata.get("authors")
        if not isinstance(authors, list):
            return []
        names: list[str] = []
        for author in authors:
            if not isinstance(author, dict):
                continue
            name = _clean(author.get("full_name"))
            if name:
                names.append(name)
        return names

    @staticmethod
    def _abstract(metadata: dict[str, Any]) -> str:
        """Return the record's primary abstract text, if any."""
        abstracts = metadata.get("abstracts")
        if not isinstance(abstracts, list):
            return ""
        for entry in abstracts:
            if isinstance(entry, dict):
                value = _clean(entry.get("value"))
                if value:
                    return value
        return ""

    @staticmethod
    def _arxiv(metadata: dict[str, Any]) -> tuple[str, list[str]]:
        """Return ``(arxiv_id, categories)`` for the record, if present."""
        eprints = metadata.get("arxiv_eprints")
        if not isinstance(eprints, list):
            return "", []
        for entry in eprints:
            if not isinstance(entry, dict):
                continue
            value = _clean(entry.get("value"))
            if value:
                categories = entry.get("categories")
                cats = (
                    [_clean(c) for c in categories if _clean(c)]
                    if isinstance(categories, list)
                    else []
                )
                return value, cats
        return "", []

    @staticmethod
    def _doi(metadata: dict[str, Any]) -> str:
        """Return the first DOI value associated with the record."""
        dois = metadata.get("dois")
        if not isinstance(dois, list):
            return ""
        for entry in dois:
            if isinstance(entry, dict):
                value = _clean(entry.get("value"))
                if value:
                    return value
        return ""

    @staticmethod
    def _journal_ref(metadata: dict[str, Any]) -> str:
        """Build a short journal reference such as ``JHEP 05 (2024) 123``."""
        infos = metadata.get("publication_info")
        if not isinstance(infos, list):
            return ""
        for info in infos:
            if not isinstance(info, dict):
                continue
            freetext = _clean(info.get("pubinfo_freetext"))
            if freetext:
                return freetext
            journal = _clean(info.get("journal_title"))
            if not journal:
                continue
            label = journal
            volume = _clean(info.get("journal_volume"))
            if volume:
                label += f" {volume}"
            year = _clean(info.get("year"))
            if year:
                label += f" ({year})"
            page = _clean(info.get("page_start")) or _clean(info.get("artid"))
            if page:
                label += f" {page}"
            return label
        return ""

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse an INSPIRE-HEP literature response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        hits = data.get("hits")
        items = hits.get("hits") if isinstance(hits, dict) else None
        if not isinstance(items, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for hit in items:
            if len(results) >= max_results:
                break
            if not isinstance(hit, dict):
                continue
            metadata = hit.get("metadata")
            if not isinstance(metadata, dict):
                continue
            title = self._title(metadata)
            record_id = self._record_id(hit)
            if not title or not record_id:
                continue

            authors = self._authors(metadata)
            abstract = self._abstract(metadata)
            arxiv_id, arxiv_categories = self._arxiv(metadata)
            doi = self._doi(metadata)
            journal = self._journal_ref(metadata)
            cited_by = metadata.get("citation_count") or 0
            doc_types = metadata.get("document_type")
            document_type = (
                [_clean(t) for t in doc_types if _clean(t)]
                if isinstance(doc_types, list)
                else []
            )

            # Abstract first (most informative), then a metadata tail.
            tail_bits: list[str] = []
            if authors:
                tail_bits.append(f"Authors: {', '.join(authors[:5])}")
            if journal:
                tail_bits.append(f"Journal: {journal}")
            if arxiv_id:
                tail_bits.append(f"arXiv: {arxiv_id}")
            if cited_by:
                tail_bits.append(f"Cited by: {cited_by}")
            snippet_parts = [abstract, " | ".join(tail_bits)]

            results.append(
                SearchResult(
                    title=title,
                    url=f"https://inspirehep.net/literature/{record_id}",
                    snippet=" | ".join(p for p in snippet_parts if p)[
                        :MAX_SNIPPET_LENGTH
                    ],
                    source="inspirehep.net",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=self._iso_date_prefix(
                        metadata.get("earliest_date")
                        if isinstance(metadata.get("earliest_date"), str)
                        else None
                    ),
                    extra={
                        "inspire_id": record_id,
                        "authors": authors,
                        "abstract": abstract,
                        "arxiv_id": arxiv_id,
                        "arxiv_categories": arxiv_categories,
                        "doi": doi,
                        "journal_ref": journal,
                        "citation_count": int(cited_by) if cited_by else 0,
                        "document_type": document_type,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search INSPIRE-HEP for literature matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        qp = {
            "q": query,
            "size": str(limit),
            "sort": "mostrecent",
            "fields": _FIELDS,
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
