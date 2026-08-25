"""UniProt protein knowledgebase search via the public, keyless REST API.

UniProt (uniprot.org, SIB/EBI/PIR) is the world's most comprehensive
catalog of protein sequence and functional information. Its read-only
REST search endpoint requires no API key:

``GET https://rest.uniprot.org/uniprotkb/search?query=QUERY&format=json&size=N``

Each hit exposes the accession (e.g. P01308), entry name (INS_HUMAN),
recommended protein name, gene name, organism, entry type (reviewed
Swiss-Prot vs. unreviewed TrEMBL), keywords, and the sequence length.
The provider is keyless and uses only the shared httpx client from the
base provider.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://rest.uniprot.org/uniprotkb/search"
_MAX_API_RESULTS = 25


class UniProtProvider(BaseProvider):
    """Search protein entries in the UniProt knowledgebase.

    Keyless. Uses the public REST API, which covers reviewed (Swiss-Prot)
    and unreviewed (TrEMBL) entries. Each hit carries the accession,
    entry name, recommended protein name, gene, organism, entry type,
    keywords, and sequence length.
    """

    name = "uniprot"
    description = (
        "Search protein entries (accession, name, gene, organism) in the "
        "UniProt knowledgebase, no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "web", "bio"]

    @staticmethod
    def _protein_name(description: object) -> str:
        """Return the recommended protein name from the proteinDescription block."""
        if not isinstance(description, dict):
            return ""
        recommended = description.get("recommendedName")
        if isinstance(recommended, dict):
            full = recommended.get("fullName")
            if isinstance(full, dict) and full.get("value"):
                return str(full["value"]).strip()
        submission = description.get("submissionNames")
        if isinstance(submission, list) and submission:
            first = submission[0]
            if isinstance(first, dict):
                full = first.get("fullName")
                if isinstance(full, dict) and full.get("value"):
                    return str(full["value"]).strip()
        return ""

    @staticmethod
    def _gene_names(item: dict[str, Any]) -> list[str]:
        """Extract the gene names from the genes block."""
        genes: list[str] = []
        for gene_group in item.get("genes") or []:
            if not isinstance(gene_group, dict):
                continue
            gene = gene_group.get("geneName")
            if isinstance(gene, dict) and gene.get("value"):
                genes.append(str(gene["value"]))
        return genes

    @staticmethod
    def _function_comment(item: dict[str, Any]) -> str:
        """Return the first FUNCTION comment text, truncated to a snippet."""
        for comment in item.get("comments") or []:
            if (
                not isinstance(comment, dict)
                or comment.get("commentType") != "FUNCTION"
            ):
                continue
            texts = comment.get("texts")
            if isinstance(texts, list) and texts:
                first = texts[0]
                if isinstance(first, dict) and first.get("value"):
                    text = " ".join(str(first["value"]).split())
                    return text[:300]
        return ""

    def _parse(
        self,
        data: dict[str, Any],
        max_results: int | None = None,
    ) -> ProviderResult:
        """Parse the UniProt search response into structured results."""
        results: list[SearchResult] = []
        limit = max_results or self._max_results
        items = data.get("results") or []

        for item in items:
            if not isinstance(item, dict):
                continue
            accession = item.get("primaryAccession") or ""
            if not accession:
                continue
            name = self._protein_name(item.get("proteinDescription"))
            if not name:
                name = item.get("uniProtkbId") or accession
            organism = (item.get("organism") or {}).get("scientificName") or ""
            gene_names = self._gene_names(item)
            entry_type = (item.get("entryType") or "").replace("UniProtKB ", "")

            snippet_parts: list[str] = []
            if organism:
                snippet_parts.append(f"Organism: {organism}")
            if gene_names:
                snippet_parts.append(f"Gene: {', '.join(gene_names)}")
            if entry_type:
                snippet_parts.append(entry_type)
            function = self._function_comment(item)
            if function:
                snippet_parts.append(function)

            sequence = item.get("sequence") or {}
            seq_length = (
                int(sequence["length"])
                if isinstance(sequence.get("length"), int)
                else 0
            )

            results.append(
                SearchResult(
                    title=name,
                    url=f"https://www.uniprot.org/uniprotkb/{accession}/entry",
                    snippet=" | ".join(snippet_parts),
                    source="uniprot.org",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "accession": accession,
                        "entry_name": item.get("uniProtkbId") or "",
                        "gene": gene_names,
                        "organism": organism,
                        "taxon_id": (item.get("organism") or {}).get("taxonId") or 0,
                        "entry_type": entry_type,
                        "sequence_length": seq_length,
                        "keywords": [
                            keyword.get("name")
                            for keyword in item.get("keywords") or []
                            if isinstance(keyword, dict) and keyword.get("name")
                        ],
                    },
                ),
            )
            if len(results) >= limit:
                break

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the UniProt knowledgebase for *query* and return protein entries."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        request_params = {
            "query": query,
            "format": "json",
            "size": limit,
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=request_params)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, max_results=limit)
