"""Search biomedical ontology terms through the EBI Ontology Lookup Service.

The EMBL-EBI Ontology Lookup Service (OLS4) exposes a public, keyless
full-text index over 250+ biomedical, biological and chemistry ontologies —
Gene Ontology, MeSH, ChEBI, HGNC, HPO, MONDO, NCIT, SNOMED and many more::

    GET https://www.ebi.ac.uk/ols4/api/search?q=<query>&rows=N&start=0

The response is ``{"response": {"numFound": N, "docs": [...]}}`` where each
document describes a single ontology term: its label, IRI, the ontology it
belongs to (with its short prefix such as ``GO`` or ``CHEBI``), the term type
(``class``, ``property``, ``individual`` or ``ontology`` for ontology-level
entries), its textual definition (for some ontologies several definitions) and
its exact, related, narrow and broad synonyms.  Terms carrying an ``obo_id``
also expose a stable identifier such as ``GO:0006915``.

This complements the terminology-adjacent providers already present (MyGene,
UniProt, PubChem, ChEMBL, RxNorm) with a vocabulary lookup: it maps free text
such as *apoptosis* or *BRCA1* to stable ontology identifiers, definitions and
synonyms, which is what agents need to ground biomedical entities.  No API key
is required.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://www.ebi.ac.uk/ols4/api/search"
_SOURCE = "ebi.ac.uk/ols4"
# Human-readable term page; the IRI is passed as a query parameter.
_TERM_URL = "https://www.ebi.ac.uk/ols4/ontologies/{ontology}/terms?iri={iri}"
# Human-readable description page of the ontology the term belongs to.
_ONTOLOGY_URL = "https://www.ebi.ac.uk/ols4/ontologies/{ontology}"
# OLS4 serves at most 100 documents per request.
_MAX_API_RESULTS = 100
# Longest description kept in a snippet so that ontology, type and synonyms
# still fit next to it.
_MAX_SNIPPET_DESCRIPTION = 240
# Number of synonyms quoted in a snippet.
_MAX_SNIPPET_SYNONYMS = 4
# Synonym fields, in the order they are merged into a single list.
_SYNONYM_FIELDS = (
    "exact_synonyms",
    "related_synonyms",
    "narrow_synonyms",
    "broad_synonyms",
)


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _int(value: object) -> int | None:
    """Return an integer field, ignoring booleans and non-integer values."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _strings(value: object) -> list[str]:
    """Return the non-empty string entries of a list-valued field."""
    if not isinstance(value, (list, tuple)):
        return []
    return [text for entry in value if (text := _clean(entry))]


def _truncate(value: str, limit: int) -> str:
    """Shorten *value* to *limit* characters, appending an ellipsis."""
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _synonyms(item: dict[str, Any]) -> list[str]:
    """Merge a term's synonym fields into one de-duplicated list.

    Exact synonyms come first, then related, narrow and broad ones; duplicates
    that differ only in case are dropped so that ``Aspirin``/``aspirin`` and
    ``NIDDM``/``niddm`` are not listed twice.
    """
    merged: list[str] = []
    seen: set[str] = set()
    for field in _SYNONYM_FIELDS:
        for synonym in _strings(item.get(field)):
            key = synonym.casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(synonym)
    return merged


def _term_url(item: dict[str, Any]) -> str:
    """Return the OLS4 term page for a document, or its IRI as a fallback."""
    iri = _clean(item.get("iri"))
    ontology = _clean(item.get("ontology_name"))
    if iri and ontology:
        return _TERM_URL.format(ontology=ontology, iri=quote(iri, safe=""))
    return iri


def _ontology_url(item: dict[str, Any]) -> str:
    """Return the OLS4 page of the ontology a document belongs to."""
    ontology = _clean(item.get("ontology_name"))
    return _ONTOLOGY_URL.format(ontology=ontology) if ontology else ""


class OlsProvider(BaseProvider):
    """Search ontology terms in the EBI Ontology Lookup Service (OLS4).

    Keyless.  *query* is matched against the labels, synonyms and definitions
    of terms from 250+ biomedical and biological ontologies, and each hit links
    to its OLS4 term page while carrying the term's IRI, ``obo_id``, ontology
    and synonyms.
    """

    name = "ols"
    description = (
        "Search the EMBL-EBI Ontology Lookup Service (OLS4), a full-text index "
        "over 250+ biomedical and biological ontologies (Gene Ontology, MeSH, "
        "ChEBI, HGNC, HPO, MONDO, NCIT and more): term labels, stable "
        "identifiers such as GO:0006915, definitions, synonyms and the "
        "ontology each term belongs to. No API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "bio", "medical", "reference"]

    @staticmethod
    def _title(item: dict[str, Any]) -> str:
        """Return a document's readable title, falling back to its identifier.

        Ontology-level entries and terms from ontologies without ``obo_id``
        have no compound identifier, so the short form and finally the IRI are
        used as fallbacks.
        """
        for field in ("label", "short_form", "obo_id", "iri"):
            title = _clean(item.get(field))
            if title:
                return title
        return ""

    def _snippet(self, item: dict[str, Any], ontology: str) -> str:
        """Compose the snippet for a single ontology term."""
        parts: list[str] = []

        descriptions = _strings(item.get("description"))
        if descriptions:
            parts.append(_truncate(descriptions[0], _MAX_SNIPPET_DESCRIPTION))

        if ontology:
            parts.append(f"Ontology: {ontology}")

        term_type = _clean(item.get("type"))
        if term_type:
            parts.append(f"Type: {term_type}")

        synonyms = _synonyms(item)[:_MAX_SNIPPET_SYNONYMS]
        if synonyms:
            parts.append(f"Synonyms: {', '.join(synonyms)}")

        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        total: int | None,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from an OLS4 term document."""
        title = self._title(item)
        url = _term_url(item)
        if not title or not url:
            return None

        ontology_name = _clean(item.get("ontology_name"))
        ontology_prefix = _clean(item.get("ontology_prefix")) or ontology_name
        short_form = _clean(item.get("short_form"))
        obo_id = _clean(item.get("obo_id"))

        return SearchResult(
            title=title,
            url=url,
            snippet=self._snippet(item, ontology_prefix),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            extra={
                "iri": _clean(item.get("iri")) or None,
                "short_form": short_form or None,
                "obo_id": obo_id or None,
                "ontology_name": ontology_name or None,
                "ontology_prefix": ontology_prefix or None,
                "ontology_url": _ontology_url(item) or None,
                "term_url": url,
                "type": _clean(item.get("type")) or None,
                "description": _strings(item.get("description")),
                "synonyms": _synonyms(item),
                "exact_synonyms": _strings(item.get("exact_synonyms")),
                "related_synonyms": _strings(item.get("related_synonyms")),
                "narrow_synonyms": _strings(item.get("narrow_synonyms")),
                "broad_synonyms": _strings(item.get("broad_synonyms")),
                "total_results": total,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse an OLS4 search response into structured results.

        OLS4's own relevance order is preserved; any other payload shape yields
        an empty result set.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        response = data.get("response")
        if not isinstance(response, dict):
            return ProviderResult(results=results)

        items = response.get("docs")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        total = _int(response.get("numFound"))
        max_results = self._max_results if limit is None else limit
        for item in items:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            built = self._build_result(item, total, len(results) + 1)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search OLS4 ontology terms for *query*.

        A blank query performs no request.  A single page is fetched, sized to
        ``num_results`` and capped at the API's ``_MAX_API_RESULTS`` maximum.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        if limit <= 0:
            return ProviderResult(results=[])

        async with self._client() as client:
            resp = await client.get(
                _SEARCH_URL,
                params={"q": cleaned, "rows": limit, "start": 0},
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit)
