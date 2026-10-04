"""Search InterPro — a protein family/domain classification database — for entries.

``ebi.ac.uk/interpro`` is the EMBL-EBI's integrated resource that classifies
proteins into families and predicts domains and functional sites by combining
the signatures of its member databases (Pfam, PANTHER, PRINTS, PROSITE, CDD,
SMART, …).  Its keyless public API exposes a full-text entry search endpoint::

    GET https://www.ebi.ac.uk/interpro/api/entry/interpro/
        ?search=QUERY&page_size=N

The response is ``{"count": N, "next": ..., "previous": ..., "results":
[{"metadata": {...}}, ...]}``.  Each hit's ``metadata`` carries a stable
InterPro accession (``IPR000023``), the entry ``name``, its ``type`` (family,
domain, repeat, homologous_superfamily, …), the ``member_databases`` it
integrates (mapping each member signature accession to its name) and the Gene
Ontology ``go_terms`` associated with it.

This complements the other biomedical providers by surfacing the curated
protein-family catalogue behind UniProt annotations.  No API key is required.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://www.ebi.ac.uk/interpro/api/entry/interpro/"
# Canonical detail page for a stable InterPro accession.
_DETAIL_URL = "https://www.ebi.ac.uk/interpro/entry/InterPro/"
# The InterPro API caps a single response at 200 entries; keep a sane ceiling.
_MAX_API_RESULTS = 100
# Member databases and GO terms listed in the snippet.
_SNIPPET_LIST_LIMIT = 3


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _member_databases(value: object) -> list[dict[str, str]]:
    """Flatten ``member_databases`` into ``{database, accession, name}`` dicts."""
    if not isinstance(value, dict):
        return []
    entries: list[dict[str, str]] = []
    for database, signatures in value.items():
        if not isinstance(signatures, dict):
            continue
        for accession, name in signatures.items():
            entries.append(
                {
                    "database": _clean(database),
                    "accession": _clean(accession),
                    "name": _clean(name),
                },
            )
    return entries


def _go_terms(value: object) -> list[dict[str, str]]:
    """Flatten ``go_terms`` into ``{identifier, name, category}`` dicts."""
    if not isinstance(value, list):
        return []
    terms: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        identifier = _clean(item.get("identifier"))
        if not identifier:
            continue
        category = item.get("category")
        category_name = ""
        if isinstance(category, dict):
            category_name = _clean(category.get("name")) or _clean(
                category.get("code"),
            )
        terms.append(
            {
                "identifier": identifier,
                "name": _clean(item.get("name")),
                "category": category_name,
            },
        )
    return terms


class InterProProvider(BaseProvider):
    """Search protein families and domains in the InterPro database.

    Keyless.  Issues a single request against the InterPro entry search API and
    returns one hit per matched entry, carrying the stable accession, entry
    type, the member-database signatures it integrates and its Gene Ontology
    terms, linking to the entry page on interpro.ebi.ac.uk.
    """

    name = "interpro"
    description = (
        "Search InterPro — a protein family, domain and functional-site "
        "classification database — for entries (stable accession, entry type, "
        "integrating member-database signatures such as Pfam/PANTHER and Gene "
        "Ontology terms) via the keyless EBI InterPro API, no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "web", "bio", "science"]

    @staticmethod
    def _snippet(
        entry_type: str,
        members: list[dict[str, str]],
        go_terms: list[dict[str, str]],
    ) -> str:
        """Compose the snippet for a single InterPro entry."""
        parts: list[str] = []
        if entry_type:
            parts.append(f"Type: {entry_type}")

        member_labels: list[str] = []
        for member in members[:_SNIPPET_LIST_LIMIT]:
            database = member["database"]
            accession = member["accession"]
            name = member["name"]
            label = f"{database}:{accession}"
            if name:
                label = f"{label} ({name})"
            member_labels.append(label)
        if member_labels:
            parts.append(f"Signatures: {'; '.join(member_labels)}")

        go_labels: list[str] = []
        for term in go_terms[:_SNIPPET_LIST_LIMIT]:
            name = term["name"]
            identifier = term["identifier"]
            go_labels.append(f"{name} ({identifier})" if name else identifier)
        if go_labels:
            parts.append(f"GO: {'; '.join(go_labels)}")

        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(self, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw InterPro entry."""
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            return None

        accession = _clean(metadata.get("accession"))
        title = _clean(metadata.get("name"))
        if not accession or not title:
            return None

        entry_type = _clean(metadata.get("type"))
        source_db = _clean(metadata.get("source_database"))
        members = _member_databases(metadata.get("member_databases"))
        go_terms = _go_terms(metadata.get("go_terms"))

        return SearchResult(
            title=title,
            url=f"{_DETAIL_URL}{quote(accession)}",
            snippet=self._snippet(entry_type, members, go_terms),
            source="ebi.ac.uk",
            rank=rank,
            provider=self.name,
            extra={
                "accession": accession,
                "type": entry_type or None,
                "source_database": source_db or None,
                "integrated": _clean(metadata.get("integrated")) or None,
                "member_databases": members,
                "go_terms": go_terms,
            },
        )

    def _parse(self, data: object, limit: int) -> list[SearchResult]:
        """Parse an InterPro search response, deduplicating by accession."""
        if not isinstance(data, dict):
            return []
        items = data.get("results")
        if not isinstance(items, list):
            return []

        results: list[SearchResult] = []
        seen: set[str] = set()
        for item in items:
            if len(results) >= limit:
                break
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata")
            if not isinstance(metadata, dict):
                continue
            accession = _clean(metadata.get("accession"))
            if not accession or accession in seen:
                continue
            seen.add(accession)
            built = self._build_result(item, len(results) + 1)
            if built is None:
                continue
            results.append(built)
        return results

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search InterPro for entries matching *query*.

        A blank query performs no request.  InterPro ranks matches by its own
        relevance order, which is preserved in the returned results.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={"search": cleaned, "page_size": limit},
            )
            resp.raise_for_status()
            data = resp.json()

        return ProviderResult(results=self._parse(data, limit))
