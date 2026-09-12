"""RCSB Protein Data Bank (PDB) structure search via the keyless RCSB APIs.

RCSB PDB (rcsb.org) is the single worldwide archive of experimentally
determined 3D structures of biological macromolecules (proteins, nucleic
acids and their complexes).  Two public, keyless JSON endpoints are used:

* ``POST https://search.rcsb.org/rcsbsearch/v2/query`` — full-text search
  that returns the matching entry identifiers (``4HHB``-style PDB ids).  The
  endpoint answers ``204 No Content`` when nothing matches.
* ``POST https://data.rcsb.org/graphql`` — a single batched GraphQL query
  that resolves the title, experimental method, resolution and release
  metadata for every matched entry in one round-trip.

This complements :mod:`metasearchmcp.providers.uniprot` (protein sequence
and annotation records) and :mod:`metasearchmcp.providers.pubmed`
(publications) by answering which *structures* match a protein, ligand or
keyword.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
_GRAPHQL_URL = "https://data.rcsb.org/graphql"
_STRUCTURE_URL = "https://www.rcsb.org/structure/"
# RCSB accepts thousands of hits; keep pages small for agent consumption.
_MAX_API_RESULTS = 50
# Maximum number of authors listed in a result snippet.
_MAX_AUTHORS_IN_SNIPPET = 3

_GRAPHQL_QUERY = """
query($ids: [String!]!) {
  entries(entry_ids: $ids) {
    rcsb_id
    struct { title }
    exptl { method }
    rcsb_entry_info {
      resolution_combined
      polymer_entity_count
      deposited_polymer_monomer_count
      experimental_method
    }
    rcsb_accession_info { initial_release_date }
    rcsb_primary_citation { rcsb_authors year journal_abbrev }
  }
}
"""


class RcsbPdbProvider(BaseProvider):
    """Search experimentally determined 3D structures in the RCSB PDB.

    Keyless.  Runs a full-text query against the RCSB search service and then
    resolves each matching PDB entry with a single batched GraphQL request.
    Results carry the structure title, experimental method, resolution,
    polymer entity/residue counts, release date and primary citation.
    """

    name = "rcsb_pdb"
    description = (
        "Search experimentally determined 3D structures (proteins, nucleic "
        "acids, complexes) in the RCSB Protein Data Bank, with title, method, "
        "resolution and citation metadata — no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "web", "bio", "protein", "structure"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if value is None:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _string_list(value: object) -> list[str]:
        """Coerce a JSON field that may be a string or list into a clean list."""
        if isinstance(value, str):
            cleaned = RcsbPdbProvider._clean_text(value)
            return [cleaned] if cleaned else []
        if not isinstance(value, list):
            return []
        return [
            cleaned
            for cleaned in (RcsbPdbProvider._clean_text(item) for item in value)
            if cleaned
        ]

    @staticmethod
    def _first_number(value: object) -> float | None:
        """Return the first numeric value from a number or list of numbers."""
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, (int, float)) and not isinstance(item, bool):
                    return float(item)
        return None

    @classmethod
    def _method_from_exptl(cls, value: object) -> str:
        """Derive the experimental method from the raw ``exptl`` array."""
        if not isinstance(value, list):
            return ""
        for item in value:
            if isinstance(item, dict):
                method = cls._clean_text(item.get("method"))
                if method:
                    return method
        return ""

    @classmethod
    def _parse_search(cls, data: object) -> list[tuple[str, float]]:
        """Return ordered ``(pdb_id, score)`` pairs from a search response."""
        if not isinstance(data, dict):
            return []
        result_set = data.get("result_set")
        if not isinstance(result_set, list):
            return []
        hits: list[tuple[str, float]] = []
        for item in result_set:
            if not isinstance(item, dict):
                continue
            identifier = cls._clean_text(item.get("identifier"))
            if not identifier:
                continue
            score = item.get("score")
            hits.append(
                (
                    identifier.upper(),
                    float(score) if isinstance(score, (int, float)) else 0.0,
                ),
            )
        return hits

    @classmethod
    def _detail_map(cls, data: object) -> dict[str, dict[str, Any]]:
        """Index a GraphQL response by PDB id -> raw entry dict."""
        if not isinstance(data, dict):
            return {}
        payload = data.get("data")
        if not isinstance(payload, dict):
            return {}
        rows = payload.get("entries")
        if not isinstance(rows, list):
            return {}
        mapping: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            pdb_id = cls._clean_text(row.get("rcsb_id"))
            if pdb_id:
                mapping[pdb_id.upper()] = row
        return mapping

    def _build_result(
        self,
        pdb_id: str,
        score: float,
        detail: object,
        rank: int,
        total: object,
    ) -> SearchResult:
        """Build a single :class:`SearchResult` from a GraphQL entry dict."""
        entry = detail if isinstance(detail, dict) else {}

        struct = entry.get("struct")
        raw_title = struct.get("title") if isinstance(struct, dict) else None
        title = self._clean_text(raw_title) or f"PDB entry {pdb_id}"

        info = entry.get("rcsb_entry_info")
        info = info if isinstance(info, dict) else {}
        method = self._clean_text(info.get("experimental_method"))
        if not method:
            method = self._method_from_exptl(entry.get("exptl"))
        resolution = self._first_number(info.get("resolution_combined"))
        polymer_entities = info.get("polymer_entity_count")
        monomer_count = info.get("deposited_polymer_monomer_count")

        accession = entry.get("rcsb_accession_info")
        accession = accession if isinstance(accession, dict) else {}
        released = self._clean_text(accession.get("initial_release_date"))
        release_date = released[:10] or None

        citation = entry.get("rcsb_primary_citation")
        citation = citation if isinstance(citation, dict) else {}
        authors = self._string_list(citation.get("rcsb_authors"))
        journal = self._clean_text(citation.get("journal_abbrev"))
        raw_year = citation.get("year")
        year = raw_year if isinstance(raw_year, int) else None

        snippet_parts: list[str] = []
        if method:
            snippet_parts.append(f"Method: {method}")
        if resolution is not None:
            snippet_parts.append(f"Resolution: {resolution:g} A")
        if isinstance(polymer_entities, int) and polymer_entities:
            snippet_parts.append(f"Polymer entities: {polymer_entities}")
        if isinstance(monomer_count, int) and monomer_count:
            snippet_parts.append(f"Residues: {monomer_count}")
        if release_date:
            snippet_parts.append(f"Released: {release_date}")
        if authors:
            label = ", ".join(authors[:_MAX_AUTHORS_IN_SNIPPET])
            if len(authors) > _MAX_AUTHORS_IN_SNIPPET:
                label += " et al."
            if journal and year:
                label += f" ({journal} {year})"
            snippet_parts.append(label)

        return SearchResult(
            title=title,
            url=f"{_STRUCTURE_URL}{pdb_id}",
            snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
            source="rcsb.org",
            rank=rank,
            provider=self.name,
            published_date=release_date,
            extra={
                "pdb_id": pdb_id,
                "score": score,
                "experimental_method": method,
                "resolution_angstrom": resolution,
                "polymer_entity_count": (
                    polymer_entities if isinstance(polymer_entities, int) else None
                ),
                "deposited_polymer_monomer_count": (
                    monomer_count if isinstance(monomer_count, int) else None
                ),
                "release_date": release_date,
                "journal": journal,
                "year": year,
                "authors": authors,
                "total_results": total if isinstance(total, int) else None,
            },
        )

    def _assemble(
        self,
        hits: list[tuple[str, float]],
        details: object,
        total: object,
        limit: int,
    ) -> ProviderResult:
        """Combine search hits with GraphQL details, preserving search order."""
        detail_map = self._detail_map(details)
        results: list[SearchResult] = []
        for pdb_id, score in hits:
            results.append(
                self._build_result(
                    pdb_id,
                    score,
                    detail_map.get(pdb_id),
                    len(results) + 1,
                    total,
                ),
            )
            if len(results) >= limit:
                break
        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the RCSB PDB for structures matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {
            "query": {
                "type": "terminal",
                "service": "full_text",
                "parameters": {"value": query},
            },
            "return_type": "entry",
            "request_options": {"paginate": {"start": 0, "rows": limit}},
        }

        async with self._client() as client:
            resp = await client.post(_SEARCH_URL, json=payload)
            resp.raise_for_status()
            # The search service answers 204 No Content when nothing matches.
            if resp.status_code == 204 or not resp.content:
                return ProviderResult(results=[])

            search_data = resp.json()
            hits = self._parse_search(search_data)[:limit]
            if not hits:
                return ProviderResult(results=[])
            total = None
            if isinstance(search_data, dict):
                total = search_data.get("total_count")

            graph = await client.post(
                _GRAPHQL_URL,
                json={
                    "query": _GRAPHQL_QUERY,
                    "variables": {"ids": [pdb_id for pdb_id, _ in hits]},
                },
            )
            graph.raise_for_status()
            details = graph.json()

        return self._assemble(hits, details, total, limit)
