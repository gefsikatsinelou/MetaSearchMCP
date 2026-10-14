"""Search open-access research articles via the keyless PLOS Search API.

`PLOS <https://plos.org/>`_ (the Public Library of Science) publishes a family
of fully open-access journals — PLOS ONE, PLOS Biology, PLOS Medicine and
others — and exposes a public Solr-backed search endpoint that needs no API
key::

    GET https://api.plos.org/search?q=QUERY&fl=...&rows=N&wt=json

Unlike the metadata-only academic providers (OpenAlex, Crossref, Semantic
Scholar), this endpoint searches the *full text* of every PLOS article.  Each
hit carries the article DOI (``id``), its title, journal, publication date,
author list and abstract.  The provider surfaces one result per article,
titled by the article title and linked to its DOI resolver URL
``https://doi.org/<doi>``.  A blank query performs no request.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.plos.org/search"
_SOURCE = "plos"
# The search endpoint's rows parameter is capped by the service; the provider
# never asks for more than this in a single request.
_MAX_API_RESULTS = 50
# Canonical resolvable link for a PLOS article, keyed by its DOI.
_DOI_URL = "https://doi.org/{doi}"
# Only the fields the provider actually uses are requested from the API.
_FIELDS = "id,title_display,journal,publication_date,author_display,abstract"
# Characters that carry special meaning to the Solr query parser; a raw user
# query containing any of them (e.g. ``CRISPR:gene``) would otherwise be
# rejected with HTTP 400, so each occurrence is backslash-escaped.
_SOLR_SPECIAL = frozenset('+-&|!(){}[]^"~*?:/\\')
# Upper bound on how many authors are spelled out in the snippet.
_MAX_SNIPPET_AUTHORS = 5
_HTML_TAG = re.compile(r"<[^>]+>")


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _first_text(value: object) -> str:
    """Return the first non-empty cleaned string from a field or list field."""
    if isinstance(value, list):
        for item in value:
            text = _clean(item)
            if text:
                return text
        return ""
    return _clean(value)


class PlosProvider(BaseProvider):
    """Search full text of open-access articles published in PLOS journals.

    Keyless.  The query is matched against the full text of every PLOS
    article and each match is returned with its journal, publication date,
    authors and abstract, linked to its DOI resolver URL.
    """

    name = "plos"
    description = (
        "Search full text of open-access research articles in PLOS journals "
        "(PLOS ONE, PLOS Biology, PLOS Medicine, ...). Each result carries the "
        "title, journal, publication date, authors and abstract. No API key "
        "required."
    )
    tags: ClassVar[list[str]] = ["academic", "web"]

    @staticmethod
    def _escape(term: str) -> str:
        """Backslash-escape Solr reserved characters in *term*."""
        return "".join(f"\\{ch}" if ch in _SOLR_SPECIAL else ch for ch in term)

    @staticmethod
    def _authors(value: object) -> list[str]:
        """Return the cleaned author names from a PLOS author list field."""
        if not isinstance(value, list):
            return []
        return [name for name in (_clean(item) for item in value) if name]

    def _build_snippet(
        self,
        journal: str,
        date: str | None,
        authors: list[str],
        abstract: str,
    ) -> str:
        """Compose a metadata-and-abstract snippet, truncated to the cap."""
        authors_str = ""
        if authors:
            authors_str = ", ".join(authors[:_MAX_SNIPPET_AUTHORS])
            if len(authors) > _MAX_SNIPPET_AUTHORS:
                authors_str += " et al."

        meta = " | ".join(part for part in (journal, date, authors_str) if part)
        if meta and abstract:
            snippet = f"{meta} — {abstract}"
        else:
            snippet = meta or abstract
        return snippet[:MAX_SNIPPET_LENGTH]

    def _build_result(self, doc: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a single article, or ``None``."""
        title = _clean(doc.get("title_display"))
        doi = _clean(doc.get("id"))
        if not title or not doi:
            return None

        journal = _clean(doc.get("journal"))
        date = self._iso_date_prefix(_clean(doc.get("publication_date")))
        authors = self._authors(doc.get("author_display"))
        abstract = _HTML_TAG.sub(" ", _first_text(doc.get("abstract")))
        abstract = _clean(abstract)
        snippet = self._build_snippet(journal, date, authors, abstract)

        return SearchResult(
            title=title,
            url=_DOI_URL.format(doi=doi),
            snippet=snippet,
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            extra={
                "doi": doi,
                "journal": journal or None,
                "authors": authors,
                "publication_date": date,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a PLOS search response into structured article results.

        The service's own relevance order is preserved; records without a
        usable title or DOI are skipped and any other payload shape yields an
        empty page.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        response = data.get("response")
        if not isinstance(response, dict):
            return ProviderResult(results=results)

        docs = response.get("docs")
        if not isinstance(docs, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for doc in docs:
            if len(results) >= max_results:
                break
            if not isinstance(doc, dict):
                continue
            built = self._build_result(doc, len(results) + 1)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the full text of PLOS articles matching *query*.

        A blank query performs no request.  Reserved Solr characters in the
        query are escaped so arbitrary user input stays valid.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={
                    "q": self._escape(cleaned),
                    "fl": _FIELDS,
                    "rows": limit,
                    "wt": "json",
                },
            )
            resp.raise_for_status()
            data: object = resp.json()

        return self._parse(data, limit)
