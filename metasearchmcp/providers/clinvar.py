"""Search ClinVar for clinically reported human genetic variants.

``clinvar`` is NCBI's public, freely accessible archive of reports on the
relationships between human genetic variants and their clinical
significance, aggregating submissions from laboratories, clinics and
databases worldwide.  Its keyless E-utilities API exposes the standard
two-step NCBI search::

    esearch.fcgi?db=clinvar&term=<query>   -> ordered list of variant UIDs
    esummary.fcgi?db=clinvar&id=<uids>     -> per-variant summary records

Each summary carries the variant title (for example
``NM_000465.4(BARD1):c.188T>G (p.Leu63Ter)``), the gene, the germline
clinical significance and review status, the associated traits (conditions)
and the molecular consequences.  The stable UID builds the canonical
variation page ``https://www.ncbi.nlm.nih.gov/clinvar/variation/<uid>/``.

This complements the PubMed, MyGene, ClinVar-adjacent and other NCBI-backed
providers with a source dedicated to clinically interpreted variants.  No
API key is required for low-volume use; set ``NCBI_API_KEY`` to raise the
request rate limit.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
_VARIATION_URL = "https://www.ncbi.nlm.nih.gov/clinvar/variation/"
# ClinVar summaries are large; cap the number of records fetched per search.
_MAX_API_RESULTS = 20
# Classification blocks checked in priority order to describe a record.
_CLASSIFICATION_FIELDS = (
    "germline_classification",
    "clinical_impact_classification",
    "oncogenicity_classification",
)


def _normalize_date(value: object) -> str | None:
    """Normalize a ClinVar ``last_evaluated`` timestamp to ``YYYY-MM-DD``.

    ClinVar reports dates as ``YYYY/MM/DD HH:MM``; ``None`` is returned when
    the value is missing or has no date portion.
    """
    if not value:
        return None
    date_part = str(value).strip().split(" ", 1)[0]
    return date_part.replace("/", "-") or None


class ClinVarProvider(BaseProvider):
    """Search clinically reported human genetic variants in ClinVar.

    Keyless.  Issues one ``esearch`` request to resolve the query to variant
    UIDs, then one ``esummary`` request for their metadata.  Each result
    carries the variant title, gene, clinical significance and review
    status, associated traits and molecular consequences, and links to the
    canonical variation page on ncbi.nlm.nih.gov.
    """

    name = "clinvar"
    description = (
        "Search ClinVar, NCBI's public archive of clinically reported human "
        "genetic variants (variant title such as `NM_000465.4(BARD1):c.188T>G`, "
        "gene, germline clinical significance and review status, associated "
        "traits, molecular consequences) via the keyless NCBI E-utilities API, "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "bio", "medical", "science"]

    def __init__(self) -> None:
        """Initialize the provider with an optional NCBI API key from settings."""
        super().__init__()
        self._api_key: str = get_settings().ncbi_api_key

    @staticmethod
    def _first_variation(item: dict[str, Any]) -> dict[str, Any]:
        """Return the first ``variation_set`` entry of a ClinVar record, if any."""
        variations = item.get("variation_set")
        if isinstance(variations, list) and variations:
            first = variations[0]
            if isinstance(first, dict):
                return first
        return {}

    @staticmethod
    def _gene_symbol(item: dict[str, Any]) -> str:
        """Return the primary gene symbol for a ClinVar record, if known."""
        primary = item.get("gene_sort")
        if primary:
            return str(primary)
        genes = item.get("genes")
        if isinstance(genes, list):
            for gene in genes:
                if isinstance(gene, dict) and gene.get("symbol"):
                    return str(gene["symbol"])
        return ""

    @staticmethod
    def _classification(item: dict[str, Any]) -> dict[str, Any]:
        """Return the most relevant classification block for a record."""
        for field in _CLASSIFICATION_FIELDS:
            block = item.get(field)
            if isinstance(block, dict) and block.get("description"):
                return block
        return {}

    @staticmethod
    def _traits(classification: dict[str, Any]) -> list[str]:
        """Return the trait (condition) names attached to a classification."""
        traits: list[str] = []
        trait_set = classification.get("trait_set")
        if isinstance(trait_set, list):
            for trait in trait_set:
                if isinstance(trait, dict) and trait.get("trait_name"):
                    name = str(trait["trait_name"]).strip()
                    if name and name not in traits:
                        traits.append(name)
        return traits

    def _build_result(
        self,
        uid: str,
        item: dict[str, Any],
        rank: int,
    ) -> SearchResult:
        """Build one :class:`SearchResult` from a parsed ClinVar summary."""
        variation = self._first_variation(item)
        gene = self._gene_symbol(item)
        classification = self._classification(item)
        traits = self._traits(classification)
        obj_type = str(item.get("obj_type") or "").strip()
        significance = str(classification.get("description") or "").strip()
        # ClinVar joins the protein change across every transcript with
        # commas; keep only the primary change to keep snippets readable.
        raw_change = str(item.get("protein_change") or "")
        protein_change = raw_change.strip().split(",")[0].strip()
        consequences = item.get("molecular_consequence_list")
        if not isinstance(consequences, list):
            consequences = []

        title = str(
            item.get("title")
            or variation.get("variation_name")
            or item.get("accession")
            or uid
        )

        snippet_parts = [part for part in (obj_type, gene) if part]
        if significance:
            snippet_parts.append(significance)
        if protein_change:
            snippet_parts.append(f"p.{protein_change}")
        snippet_parts.extend(traits)

        return SearchResult(
            title=title,
            url=f"{_VARIATION_URL}{uid}/",
            snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
            source="ncbi.nlm.nih.gov",
            rank=rank,
            provider=self.name,
            published_date=_normalize_date(classification.get("last_evaluated")),
            extra={
                "uid": uid,
                "accession": item.get("accession") or None,
                "obj_type": obj_type or None,
                "gene": gene or None,
                "classification": significance or None,
                "review_status": classification.get("review_status") or None,
                "traits": traits,
                "variant_type": variation.get("variant_type") or None,
                "cdna_change": variation.get("cdna_change") or None,
                "protein_change": protein_change or None,
                "molecular_consequence": [str(c) for c in consequences],
            },
        )

    def _parse(self, data: dict[str, Any], ids: list[str]) -> ProviderResult:
        """Parse an E-utilities esummary response into structured results."""
        result_map = data.get("result", {})
        if not isinstance(result_map, dict):
            return ProviderResult()

        results: list[SearchResult] = []
        for uid in ids:
            item = result_map.get(uid)
            if not isinstance(item, dict) or not item:
                continue
            results.append(self._build_result(uid, item, len(results) + 1))
        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search ClinVar for clinically reported variants matching *query*.

        A blank query performs no request.  Transient HTTP failures are
        raised for the orchestrator to handle and retry.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult()

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        esearch_params: dict[str, Any] = {
            "db": "clinvar",
            "term": cleaned,
            "retmax": limit,
            "retmode": "json",
            "sort": "relevance",
        }
        if self._api_key:
            esearch_params["api_key"] = self._api_key

        async with self._client() as client:
            search_resp = await client.get(_ESEARCH_URL, params=esearch_params)
            search_resp.raise_for_status()
            ids = search_resp.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                return ProviderResult()

            esummary_params: dict[str, Any] = {
                "db": "clinvar",
                "id": ",".join(ids),
                "retmode": "json",
            }
            if self._api_key:
                esummary_params["api_key"] = self._api_key

            summary_resp = await client.get(_ESUMMARY_URL, params=esummary_params)
            summary_resp.raise_for_status()
            summary_data = summary_resp.json()

        return self._parse(summary_data, ids)
