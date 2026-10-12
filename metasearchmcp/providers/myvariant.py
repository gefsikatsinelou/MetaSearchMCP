"""MyVariant.info genetic variant annotation search via the BioThings API.

MyVariant.info (myvariant.info) is a BioThings project that aggregates
variant annotations from ClinVar, dbSNP, dbNSFP, CADD, SnpEff, gnomAD and
many other sources into a single keyless REST endpoint.  Its v1 query
endpoint returns JSON:

``GET https://myvariant.info/v1/query?q=QUERY&size=N&fields=...``

Queries may target a dbSNP rsID (``rs113488022``), a gene symbol, an HGVS
name, or a specific genomic coordinate.  Each hit carries the variant id
(e.g. ``chr7:g.140453136A>G``), associated gene names, protein/coding
changes, dbSNP rsID, ClinVar clinical significance and conditions, and a
CADD deleteriousness score.  This complements
:mod:`metasearchmcp.providers.mygene` (which indexes *genes*) and
:mod:`metasearchmcp.providers.clinvar` (which indexes ClinVar releases) by
answering which specific genetic variants match a query.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://myvariant.info/v1/query"
_FIELDS = (
    "_id,dbnsfp.genename,dbnsfp.hgvsp,dbnsfp.hgvsc,"
    "clinvar.gene.symbol,clinvar.rcv.clinical_significance,"
    "clinvar.rcv.conditions.name,dbsnp.rsid,"
    "snpeff.ann.hgvs_p,snpeff.ann.gene_name,cadd.phred"
)
# MyVariant.info accepts up to 1000 hits per request; keep pages small for agents.
_MAX_API_RESULTS = 50
# Maximum number of clinical significances / conditions listed in a snippet.
_MAX_SIGNIFICANCES_IN_SNIPPET = 4
_MAX_CONDITIONS_IN_SNIPPET = 3


class MyVariantProvider(BaseProvider):
    """Search genetic variant annotations in MyVariant.info.

    Keyless.  Uses the public BioThings MyVariant.info v1 query API.  Each
    result carries the variant id, associated gene, protein/coding change,
    dbSNP rsID, ClinVar clinical significance and conditions, and CADD score.
    """

    name = "myvariant"
    description = (
        "Search genetic variant annotations (rsID, gene, protein change, "
        "ClinVar significance, CADD score) via the BioThings MyVariant.info "
        "API — no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "web", "bio", "genomics"]

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
            cleaned = MyVariantProvider._clean_text(value)
            return [cleaned] if cleaned else []
        if not isinstance(value, list):
            return []
        return [
            cleaned
            for cleaned in (MyVariantProvider._clean_text(item) for item in value)
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
    def _as_dict_list(value: object) -> list[dict[str, Any]]:
        """Coerce a value that may be a dict or list of dicts into a list of dicts."""
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []

    @staticmethod
    def _condition_names(value: object) -> list[str]:
        """Extract de-duplicated condition names from a ClinVar conditions field.

        The field may be a single string, a list of strings, a dict with a
        ``name`` key, or a list of such dicts.
        """
        names: list[str] = []

        def add(raw: object) -> None:
            cleaned = MyVariantProvider._clean_text(raw)
            if cleaned and cleaned not in names:
                names.append(cleaned)

        if isinstance(value, str):
            add(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    add(item)
                elif isinstance(item, dict):
                    add(item.get("name"))
        elif isinstance(value, dict):
            add(value.get("name"))

        return names

    def _clinvar_summary(self, clinvar: dict[str, Any]) -> tuple[list[str], list[str]]:
        """Return (clinical_significances, condition_names) from a ClinVar block."""
        significances: list[str] = []
        conditions: list[str] = []
        for rcv in self._as_dict_list(clinvar.get("rcv")):
            significance = self._clean_text(rcv.get("clinical_significance"))
            if significance and significance not in significances:
                significances.append(significance)
            for name in self._condition_names(rcv.get("conditions")):
                if name not in conditions:
                    conditions.append(name)
        return significances, conditions

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a MyVariant.info query response into structured results."""
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
            variant_id = self._clean_text(hit.get("_id"))
            if not variant_id:
                continue

            dbnsfp = self._first_dict(hit.get("dbnsfp"))
            clinvar = self._first_dict(hit.get("clinvar"))
            snpeff = self._first_dict(hit.get("snpeff"))
            cadd = self._first_dict(hit.get("cadd"))

            gene_names = self._string_list(dbnsfp.get("genename"))
            clinvar_gene = self._clean_text(
                self._first_dict(clinvar.get("gene")).get("symbol"),
            )
            gene = gene_names[0] if gene_names else clinvar_gene

            hgvsp = self._string_list(dbnsfp.get("hgvsp"))
            hgvsc = self._string_list(dbnsfp.get("hgvsc"))
            snpeff_anns = self._as_dict_list(snpeff.get("ann"))
            snpeff_hgvsp = ""
            snpeff_gene = ""
            if snpeff_anns:
                snpeff_hgvsp = self._clean_text(snpeff_anns[0].get("hgvs_p"))
                snpeff_gene = self._clean_text(snpeff_anns[0].get("gene_name"))

            protein_change = hgvsp[0] if hgvsp else snpeff_hgvsp
            coding_change = hgvsc[0] if hgvsc else ""
            if not gene:
                gene = snpeff_gene

            rsid = self._clean_text(self._first_dict(hit.get("dbsnp")).get("rsid"))
            cadd_phred = cadd.get("phred")
            significances, conditions = self._clinvar_summary(clinvar)

            change = protein_change or coding_change
            if gene and change:
                title = f"{gene} {change}"
            elif gene:
                title = gene
            else:
                title = variant_id

            snippet_parts: list[str] = []
            if gene:
                snippet_parts.append(f"Gene: {gene}")
            if protein_change:
                snippet_parts.append(f"Protein change: {protein_change}")
            if coding_change:
                snippet_parts.append(f"Coding change: {coding_change}")
            if rsid:
                snippet_parts.append(f"rsID: {rsid}")
            if significances:
                snippet_parts.append(
                    f"Clinical significance: "
                    f"{', '.join(significances[:_MAX_SIGNIFICANCES_IN_SNIPPET])}",
                )
            if conditions:
                snippet_parts.append(
                    f"Conditions: {', '.join(conditions[:_MAX_CONDITIONS_IN_SNIPPET])}",
                )
            if isinstance(cadd_phred, (int, float)):
                snippet_parts.append(f"CADD phred: {cadd_phred}")

            results.append(
                SearchResult(
                    title=title,
                    url=(
                        f"https://www.ncbi.nlm.nih.gov/snp/{rsid}"
                        if rsid
                        else f"https://myvariant.info/v1/variant/{variant_id}"
                    ),
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source="myvariant.info",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "variant_id": variant_id,
                        "gene": gene,
                        "genes": gene_names,
                        "rsid": rsid,
                        "hgvsp": protein_change,
                        "hgvsc": coding_change,
                        "clinical_significance": significances,
                        "conditions": conditions,
                        "cadd_phred": (
                            cadd_phred if isinstance(cadd_phred, (int, float)) else None
                        ),
                        "score": hit.get("_score"),
                        "total_results": total,
                    },
                ),
            )
            if len(results) >= max_results:
                break

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search MyVariant.info for genetic variants matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        request_params = {
            "q": query,
            "size": limit,
            "fields": _FIELDS,
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=request_params)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
