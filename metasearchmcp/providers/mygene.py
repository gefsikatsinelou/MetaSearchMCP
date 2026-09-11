"""MyGene.info gene annotation search via the keyless BioThings REST API.

MyGene.info (mygene.info) is a BioThings project that provides fast,
programmatic access to gene annotations aggregated from NCBI Entrez Gene,
Ensembl, UniProt, RefSeq and others.  Its v3 query endpoint is keyless and
returns JSON:

``GET https://mygene.info/v3/query?q=QUERY&size=N&species=all&fields=...``

The endpoint searches human genes by default, so this provider always sends
``species=all`` to cover every organism.  Each hit carries the Entrez gene
id, official symbol, full name, organism taxid, gene type, chromosome
location, aliases, Ensembl/UniProt cross-references and a functional
summary.  This complements :mod:`metasearchmcp.providers.uniprot` (which
indexes *proteins*) and :mod:`metasearchmcp.providers.pubmed` (which indexes
*publications*) by answering which genes match a symbol or name.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://mygene.info/v3/query"
_FIELDS = (
    "symbol,name,entrezgene,taxid,type_of_gene,summary,"
    "genomic_pos,alias,ensembl,uniprot"
)
# MyGene.info accepts up to 1000 hits per request; keep pages small for agents.
_MAX_API_RESULTS = 50
# Maximum number of gene aliases listed in a result snippet.
_MAX_ALIASES_IN_SNIPPET = 4

# Common model organisms, used to label a taxid with a friendly name.
_ORGANISMS: dict[int, str] = {
    9606: "human",
    10090: "mouse",
    10116: "rat",
    9544: "rhesus macaque",
    9913: "cattle",
    9823: "pig",
    9615: "dog",
    9031: "chicken",
    7955: "zebrafish",
    7227: "fruit fly",
    6239: "C. elegans",
    559292: "S. cerevisiae",
    3702: "A. thaliana",
}


class MyGeneProvider(BaseProvider):
    """Search gene annotations (symbol, name, organism, location) in MyGene.info.

    Keyless.  Uses the public BioThings MyGene.info v3 query API across all
    organisms.  Each result carries the Entrez gene id, official symbol and
    name, organism, gene type, chromosome location, aliases and cross-references.
    """

    name = "mygene"
    description = (
        "Search gene annotations (symbol, full name, organism, chromosome, "
        "aliases) via the BioThings MyGene.info API — no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "web", "bio", "gene"]

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
            cleaned = MyGeneProvider._clean_text(value)
            return [cleaned] if cleaned else []
        if not isinstance(value, list):
            return []
        return [
            cleaned
            for cleaned in (MyGeneProvider._clean_text(item) for item in value)
            if cleaned
        ]

    @staticmethod
    def _first_dict(value: object) -> dict[str, Any]:
        """Return the first dict from a value that may be a dict or a list."""
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    return item
        return {}

    @staticmethod
    def _swiss_prot(uniprot: object) -> str:
        """Return the primary UniProt Swiss-Prot accession, if any."""
        accessions = MyGeneProvider._string_list(
            MyGeneProvider._first_dict(uniprot).get("Swiss-Prot"),
        )
        return accessions[0] if accessions else ""

    @staticmethod
    def _organism(taxid: int) -> str:
        """Return a label like ``human (9606)`` for a taxonomy id."""
        if not taxid:
            return ""
        name = _ORGANISMS.get(taxid)
        return f"{name} ({taxid})" if name else f"taxid {taxid}"

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a MyGene.info query response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        hits = data.get("hits")
        if not isinstance(hits, list):
            return ProviderResult(results=results)

        total = data.get("total")
        max_results = limit or self._max_results

        for hit in hits:
            if not isinstance(hit, dict):
                continue
            gene_id = self._clean_text(hit.get("_id"))
            symbol = self._clean_text(hit.get("symbol"))
            name = self._clean_text(hit.get("name"))
            title = symbol or name
            if not title:
                continue
            if symbol and name and name != symbol:
                title = f"{symbol} ({name})"

            position = self._first_dict(hit.get("genomic_pos"))
            chromosome = self._clean_text(position.get("chr"))
            ensembl_gene = self._clean_text(position.get("ensemblgene")) or (
                self._clean_text(self._first_dict(hit.get("ensembl")).get("gene"))
            )
            start = position.get("start")
            end = position.get("end")
            aliases = self._string_list(hit.get("alias"))
            gene_type = self._clean_text(hit.get("type_of_gene"))
            raw_taxid = hit.get("taxid")
            taxid = raw_taxid if isinstance(raw_taxid, int) else 0
            organism = self._organism(taxid)
            summary = self._clean_text(hit.get("summary"))
            uniprot = self._swiss_prot(hit.get("uniprot"))
            entrezgene = self._clean_text(hit.get("entrezgene")) or gene_id

            snippet_parts: list[str] = []
            if organism:
                snippet_parts.append(f"Organism: {organism}")
            if gene_type:
                snippet_parts.append(f"Type: {gene_type}")
            if chromosome:
                snippet_parts.append(f"Chromosome: {chromosome}")
            if aliases:
                snippet_parts.append(
                    f"Aliases: {', '.join(aliases[:_MAX_ALIASES_IN_SNIPPET])}",
                )
            if summary:
                snippet_parts.append(summary)

            results.append(
                SearchResult(
                    title=title,
                    url=(
                        f"https://www.ncbi.nlm.nih.gov/gene/{entrezgene}"
                        if entrezgene
                        else f"https://mygene.info/v3/gene/{gene_id}"
                    ),
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source="mygene.info",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "gene_id": gene_id,
                        "symbol": symbol,
                        "name": name,
                        "entrezgene": entrezgene,
                        "taxid": taxid,
                        "organism": organism,
                        "type_of_gene": gene_type,
                        "chromosome": chromosome,
                        "genomic_start": start if isinstance(start, int) else None,
                        "genomic_end": end if isinstance(end, int) else None,
                        "ensembl_gene": ensembl_gene,
                        "uniprot": uniprot,
                        "aliases": aliases,
                        "total_results": total,
                    },
                ),
            )
            if len(results) >= max_results:
                break

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search MyGene.info for genes matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        request_params = {
            "q": query,
            "size": limit,
            "species": "all",
            "fields": _FIELDS,
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=request_params)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
