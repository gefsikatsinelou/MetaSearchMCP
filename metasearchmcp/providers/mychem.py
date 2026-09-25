"""MyChem.info chemical and drug annotation search via the keyless BioThings API.

MyChem.info (mychem.info) is a BioThings project that integrates chemical and
drug annotations from ChEMBL, DrugBank, ChEBI, DrugCentral, PubChem, UNII,
NDC, GtoPdb, PharmGKB, UMLS and others behind a single keyless JSON API::

    GET https://mychem.info/v1/query?q=QUERY&size=N&fields=...

Every hit is keyed by the compound's InChIKey and carries the preferred drug
name, the molecular formula and weight, the canonical SMILES, the CAS
registry number, the ChEMBL approval phase and first-approval year, the
withdrawal flag, an FDA/NCIT definition where available, and cross references
(PubChem CID, ChEMBL id, DrugBank accession, ChEBI id, RxNorm RxCUI, UNII).

This complements :mod:`metasearchmcp.providers.mygene` (which indexes
*genes*), :mod:`metasearchmcp.providers.pubchem` and
:mod:`metasearchmcp.providers.chembl` (single-source compound lookups) by
answering which drug or chemical matches a name and how the same substance is
identified across the major chemical databases.  No API key is required.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://mychem.info/v1/query"
# Only the fields needed for a compact agent-facing record are requested;
# MyChem.info returns every annotation for a substance otherwise.
_FIELDS = ",".join(
    (
        "unii.display_name",
        "unii.utf8_display_name",
        "unii.inchikey",
        "unii.molecular_formula",
        "unii.smiles",
        "unii.registry_number",
        "unii.rxcui",
        "unii.pubchem",
        "unii.ncit",
        "unii.substance_type",
        "unii.ncit_description",
        "chembl.pref_name",
        "chembl.molecule_chembl_id",
        "chembl.max_phase",
        "chembl.molecule_type",
        "chembl.smiles",
        "chembl.first_approval",
        "chembl.withdrawn_flag",
        "drugbank.id",
        "drugbank.name",
        "drugbank.cas",
        "chebi.id",
        "chebi.name",
        "chebi.formula",
        "chebi.mass",
        "chebi.definition",
        "drugcentral.id",
        "pubchem.cid",
        "pubchem.molecular_weight",
        "pubchem.xlogp",
    ),
)
# MyChem.info accepts up to 1000 hits per request; keep pages small for agents.
_MAX_API_RESULTS = 50
# Characters of the compound definition copied into the snippet.
_SNIPPET_DESCRIPTION_LENGTH = 180
# Characters of the SMILES string copied into the snippet.
_SNIPPET_SMILES_LENGTH = 60
# Annotation sources reported per hit, in display order.
_SOURCES = (
    "chembl",
    "drugbank",
    "chebi",
    "drugcentral",
    "unii",
    "pubchem",
    "ndc",
    "ginas",
    "gtopdb",
    "pharmgkb",
    "sider",
    "aeolus",
    "umls",
    "unichem",
)


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _first_dict(value: object) -> dict[str, Any]:
    """Return the first dict from a value that may be a dict or a list."""
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


def _as_float(value: object) -> float | None:
    """Coerce a JSON number or numeric string to ``float``, else ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _as_int(value: object) -> int | None:
    """Coerce a JSON number or numeric string to ``int``, else ``None``."""
    number = _as_float(value)
    return int(number) if number is not None else None


class MyChemProvider(BaseProvider):
    """Search chemical and drug annotations (identifiers, formula, approval).

    Keyless.  Uses the public BioThings MyChem.info v1 query API.  Each result
    carries the preferred substance name, molecular formula and weight, SMILES,
    CAS registry number, approval phase and first-approval year, withdrawal
    status and cross references to PubChem, ChEMBL, DrugBank, ChEBI, RxNorm and
    UNII.
    """

    name = "mychem"
    description = (
        "Search chemical and drug annotations (identifiers, molecular formula, "
        "SMILES, CAS, approval phase, cross-references) via the BioThings "
        "MyChem.info API — no API key required."
    )
    tags: ClassVar[list[str]] = ["drugs", "chemistry", "bio", "academic", "web"]

    @staticmethod
    def _name(hit: dict[str, Any]) -> str:
        """Return the preferred substance name from the richest source."""
        chembl = _first_dict(hit.get("chembl"))
        drugbank = _first_dict(hit.get("drugbank"))
        unii = _first_dict(hit.get("unii"))
        chebi = _first_dict(hit.get("chebi"))
        for candidate in (
            chembl.get("pref_name"),
            drugbank.get("name"),
            unii.get("display_name"),
            unii.get("utf8_display_name"),
            chebi.get("name"),
        ):
            cleaned = _clean(candidate)
            if cleaned:
                return cleaned
        return ""

    @staticmethod
    def _definition(hit: dict[str, Any]) -> str:
        """Return a short description of the substance, if any source has one."""
        unii = _first_dict(hit.get("unii"))
        chebi = _first_dict(hit.get("chebi"))
        for candidate in (unii.get("ncit_description"), chebi.get("definition")):
            cleaned = _clean(candidate)
            if cleaned:
                return cleaned
        return ""

    @staticmethod
    def _identifiers(hit: dict[str, Any]) -> dict[str, Any]:
        """Collect the cross-database identifiers of a substance."""
        chembl = _first_dict(hit.get("chembl"))
        drugbank = _first_dict(hit.get("drugbank"))
        chebi = _first_dict(hit.get("chebi"))
        unii = _first_dict(hit.get("unii"))
        pubchem = _first_dict(hit.get("pubchem"))
        drugcentral = _first_dict(hit.get("drugcentral"))
        return {
            "chembl_id": _clean(chembl.get("molecule_chembl_id")),
            "drugbank_id": _clean(drugbank.get("id")),
            "chebi_id": _clean(chebi.get("id")),
            "pubchem_cid": _as_int(unii.get("pubchem")) or _as_int(pubchem.get("cid")),
            "rxcui": _clean(unii.get("rxcui")),
            "unii": _clean(unii.get("unii")),
            "drugcentral_id": _as_int(drugcentral.get("id")),
        }

    @staticmethod
    def _url(inchikey: str, identifiers: dict[str, Any]) -> str:
        """Return the most useful landing page for a substance."""
        cid = identifiers.get("pubchem_cid")
        if cid:
            return f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"
        chembl_id = identifiers.get("chembl_id")
        if chembl_id:
            return f"https://www.ebi.ac.uk/chembl/compound_report_card/{chembl_id}/"
        return f"https://mychem.info/v1/chem/{inchikey}"

    @staticmethod
    def _snippet(
        definition: str,
        formula: str,
        molecular_weight: float | None,
        cas: str,
        smiles: str,
        max_phase: float | None,
        first_approval: int | None,
        withdrawn: bool,
        identifiers: dict[str, Any],
        sources: list[str],
    ) -> str:
        """Compose the snippet for a single substance."""
        parts: list[str] = []
        if definition:
            parts.append(definition[:_SNIPPET_DESCRIPTION_LENGTH])
        if formula:
            parts.append(f"Formula: {formula}")
        if molecular_weight is not None:
            parts.append(f"MW: {molecular_weight:g}")
        if cas:
            parts.append(f"CAS: {cas}")
        if max_phase is not None:
            approval = f"Max phase: {max_phase:g}"
            if first_approval:
                approval += f" (first approved {first_approval})"
            parts.append(approval)
        if withdrawn:
            parts.append("Withdrawn")
        if smiles:
            parts.append(f"SMILES: {smiles[:_SNIPPET_SMILES_LENGTH]}")
        labels = [
            f"{label} {identifiers[key]}"
            for key, label in (
                ("pubchem_cid", "PubChem CID"),
                ("chembl_id", "ChEMBL"),
                ("drugbank_id", "DrugBank"),
                ("chebi_id", "ChEBI"),
                ("rxcui", "RxCUI"),
                ("unii", "UNII"),
            )
            if identifiers.get(key)
        ]
        if labels:
            parts.append(" | ".join(labels))
        if sources:
            parts.append(f"Sources: {', '.join(sources)}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(self, hit: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw MyChem.info hit."""
        inchikey = _clean(hit.get("_id"))
        name = self._name(hit)
        title = name or inchikey
        if not title:
            return None

        chembl = _first_dict(hit.get("chembl"))
        unii = _first_dict(hit.get("unii"))
        chebi = _first_dict(hit.get("chebi"))
        drugbank = _first_dict(hit.get("drugbank"))
        pubchem = _first_dict(hit.get("pubchem"))

        identifiers = self._identifiers(hit)
        formula = (
            _clean(chebi.get("formula"))
            or _clean(unii.get("molecular_formula"))
            or _clean(pubchem.get("molecular_formula"))
        )
        molecular_weight = _as_float(pubchem.get("molecular_weight")) or _as_float(
            chebi.get("mass"),
        )
        cas = _clean(unii.get("registry_number")) or _clean(drugbank.get("cas"))
        smiles = _clean(unii.get("smiles")) or _clean(chembl.get("smiles"))
        max_phase = _as_float(chembl.get("max_phase"))
        first_approval = _as_int(chembl.get("first_approval"))
        withdrawn = bool(chembl.get("withdrawn_flag"))
        molecule_type = _clean(chembl.get("molecule_type"))
        ncit = _clean(unii.get("ncit"))
        sources = [source for source in _SOURCES if source in hit]

        return SearchResult(
            title=title,
            url=self._url(inchikey, identifiers),
            snippet=self._snippet(
                self._definition(hit),
                formula,
                molecular_weight,
                cas,
                smiles,
                max_phase,
                first_approval,
                withdrawn,
                identifiers,
                sources,
            ),
            source="mychem.info",
            rank=rank,
            provider=self.name,
            extra={
                "inchikey": inchikey or None,
                "name": name or None,
                "formula": formula or None,
                "molecular_weight": molecular_weight,
                "smiles": smiles or None,
                "cas": cas or None,
                "unii": identifiers["unii"] or None,
                "rxcui": identifiers["rxcui"] or None,
                "pubchem_cid": identifiers["pubchem_cid"],
                "chembl_id": identifiers["chembl_id"] or None,
                "drugbank_id": identifiers["drugbank_id"] or None,
                "chebi_id": identifiers["chebi_id"] or None,
                "drugcentral_id": identifiers["drugcentral_id"],
                "max_phase": max_phase,
                "first_approval": first_approval,
                "withdrawn": withdrawn,
                "molecule_type": molecule_type or None,
                "substance_type": _clean(unii.get("substance_type")) or None,
                "ncit": ncit or None,
                "sources": sources,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a MyChem.info query response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        hits = data.get("hits")
        if not isinstance(hits, list):
            return ProviderResult(results=results)

        total = data.get("total")
        max_results = limit or self._max_results
        seen: set[str] = set()

        for hit in hits:
            if len(results) >= max_results:
                break
            if not isinstance(hit, dict):
                continue
            # A substance is keyed by its InChIKey.
            inchikey = _clean(hit.get("_id"))
            if inchikey:
                if inchikey in seen:
                    continue
                seen.add(inchikey)
            built = self._build_result(hit, len(results) + 1)
            if built is None:
                continue
            built.extra["total_results"] = total
            results.append(built)
        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search MyChem.info for chemicals and drugs matching *query*.

        A blank query performs no request.  The API ranks hits by its own
        relevance score, which is preserved in the returned order.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={"q": cleaned, "size": limit, "fields": _FIELDS},
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
