"""ChEMBL drug and bioactive molecule search via the keyless public API.

``GET https://www.ebi.ac.uk/chembl/api/data/molecule/search.json?q=QUERY``
returns matching drug-like molecules from the ChEMBL database (EMBL-EBI),
which aggregates bioactivity data from medicinal chemistry literature. No
API key or authentication is required.

Each hit exposes the preferred name, ChEMBL id, molecular formula, weight,
canonical SMILES, ATC classifications, max clinical phase, first approval
year, and trade names — enough to answer drug lookup questions directly
without follow-up requests.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://www.ebi.ac.uk/chembl/api/data/molecule/search.json"
# The ChEMBL API caps page size at 100 records per request.
_MAX_API_RESULTS = 50


class ChEMBLProvider(BaseProvider):
    """Search drug-like molecules in the ChEMBL database.

    Uses the keyless public REST API, which requires no authentication and
    returns rich drug metadata: preferred name, ChEMBL id, molecular formula,
    weight, canonical SMILES, ATC classification codes, max clinical phase,
    first approval year, and trade names.
    """

    name = "chembl"
    description = (
        "Search drugs and bioactive molecules in the ChEMBL database — "
        "molecular formula, SMILES, ATC codes, and approval status via the keyless API."
    )
    tags: ClassVar[list[str]] = ["drugs", "pharma", "academic", "web"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _properties(molecule: dict[str, Any]) -> dict[str, Any]:
        """Extract the molecular-properties sub-object, guarding against junk."""
        props = molecule.get("molecule_properties")
        return props if isinstance(props, dict) else {}

    def _parse(self, data: Any, limit: int | None = None) -> ProviderResult:
        """Parse the molecule/search.json response into structured results."""
        results: list[SearchResult] = []
        max_results = limit or self._max_results
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        molecules = data.get("molecules")
        if not isinstance(molecules, list):
            return ProviderResult(results=results)

        for i, item in enumerate(molecules, start=1):
            if i > max_results:
                break
            if not isinstance(item, dict):
                continue

            title = self._clean(item.get("pref_name"))
            chembl_id = self._clean(item.get("molecule_chembl_id"))
            if not title or not chembl_id:
                continue

            props = self._properties(item)
            formula = self._clean(props.get("full_molformula"))
            weight = self._clean(props.get("full_mwt"))
            structures = item.get("molecule_structures") or {}
            smiles = self._clean(structures.get("canonical_smiles"))
            atc = item.get("atc_classifications") or []
            atc_codes = sorted({str(code).strip() for code in atc if str(code).strip()})
            synonyms = item.get("molecule_synonyms") or []
            trade_names = sorted(
                {
                    str(syn.get("molecule_synonym")).strip()
                    for syn in synonyms
                    if isinstance(syn, dict)
                    and str(syn.get("molecule_synonym")).strip()
                },
            )
            max_phase = item.get("max_phase")
            first_approval = item.get("first_approval")
            withdrawn = bool(item.get("withdrawn_flag"))

            snippet_parts: list[str] = []
            if formula:
                snippet_parts.append(f"Formula: {formula}")
            if weight:
                snippet_parts.append(f"MW: {weight}")
            if atc_codes:
                snippet_parts.append(f"ATC: {', '.join(atc_codes[:4])}")
            if max_phase is not None:
                snippet_parts.append(f"Max phase: {max_phase}")

            results.append(
                SearchResult(
                    title=title,
                    url=f"https://www.ebi.ac.uk/chembl/report_card/{chembl_id}/",
                    snippet=" | ".join(snippet_parts),
                    source="ebi.ac.uk/chembl",
                    rank=i,
                    provider=self.name,
                    published_date=(
                        str(first_approval) if first_approval is not None else None
                    ),
                    extra={
                        "chembl_id": chembl_id,
                        "molecular_formula": formula,
                        "molecular_weight": weight,
                        "canonical_smiles": smiles,
                        "atc_codes": atc_codes,
                        "trade_names": trade_names[:5],
                        "max_phase": str(max_phase) if max_phase is not None else "",
                        "first_approval": (
                            str(first_approval) if first_approval is not None else ""
                        ),
                        "withdrawn": withdrawn,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the ChEMBL database for molecules matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={"q": query, "limit": str(limit)},
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit)
