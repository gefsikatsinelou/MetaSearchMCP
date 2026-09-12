"""PubChem chemical compound search via the public, keyless PUG REST API.

PubChem (pubchem.ncbi.nlm.nih.gov, maintained by NCBI) is the world's largest
open collection of chemical substances, their structures and their biological
activities.  Its PUG REST interface is open and requires no API key:

``GET .../rest/pug/compound/name/{name}/property/{props}/JSON``
``GET .../rest/autocomplete/compound/{name}/json?limit=N``

The first endpoint resolves a compound name (or synonym) to its PubChem
record(s) and returns the molecular formula, molecular weight, canonical
SMILES, IUPAC name and InChIKey; the second supplies related compound names,
which are surfaced through ``ProviderResult.suggestions``.  When no exact
compound name matches, the autocomplete names are returned as lightweight
results so an approximate query still yields something usable.

This complements :mod:`metasearchmcp.providers.chembl` (bioactivity and drug
records) with the reference chemical structure database.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar
from urllib.parse import quote

import httpx

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest"
_PROPERTY_URL = _API_BASE + "/pug/compound/name/{name}/property/{props}/JSON"
_AUTOCOMPLETE_URL = _API_BASE + "/autocomplete/compound/{name}/json"
_RECORD_URL = "https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"
_SEARCH_URL = "https://pubchem.ncbi.nlm.nih.gov/#query={name}"
_SOURCE = "pubchem.ncbi.nlm.nih.gov"
# Properties fetched for every matched compound, kept compact for agents.
_PROPERTIES = (
    "Title,MolecularFormula,MolecularWeight,CanonicalSMILES,IUPACName,InChIKey"
)
# Number of related compound names requested from the autocomplete endpoint.
_MAX_SUGGESTIONS = 8


def _text(value: object) -> str:
    """Coerce a PubChem field into a whitespace-collapsed string."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _encode(name: str) -> str:
    """Percent-encode *name* for safe use as a single PubChem path segment."""
    return quote(name.strip(), safe="")


class PubChemProvider(BaseProvider):
    """Search chemical compounds in the PubChem database.

    Keyless.  Uses the public PUG REST API to resolve a compound name to its
    record(s) and reports the molecular formula, molecular weight, canonical
    SMILES, IUPAC name and InChIKey, plus related compound-name suggestions.
    """

    name = "pubchem"
    description = (
        "Search chemical compounds in PubChem — molecular formula, weight, "
        "canonical SMILES, IUPAC name and InChIKey via the keyless PUG REST API."
    )
    tags: ClassVar[list[str]] = ["chemistry", "science", "bio", "web"]

    @staticmethod
    def _property_records(data: object) -> list[dict[str, Any]]:
        """Extract the list of property dicts from a PUG REST response."""
        if not isinstance(data, dict):
            return []
        table = data.get("PropertyTable")
        if not isinstance(table, dict):
            return []
        records = table.get("Properties")
        if not isinstance(records, list):
            return []
        return [record for record in records if isinstance(record, dict)]

    @staticmethod
    def _suggestion_names(data: object) -> list[str]:
        """Extract compound-name suggestions from an autocomplete response."""
        if not isinstance(data, dict):
            return []
        terms = data.get("dictionary_terms")
        if not isinstance(terms, dict):
            return []
        compounds = terms.get("compound")
        if not isinstance(compounds, list):
            return []
        names = (_text(name) for name in compounds)
        return [name for name in names if name]

    def _record(self, props: dict[str, Any], rank: int) -> SearchResult | None:
        """Build a :class:`SearchResult` from one PubChem property record."""
        cid = props.get("CID")
        title = _text(props.get("Title"))
        if not isinstance(cid, int) or not title:
            return None

        formula = _text(props.get("MolecularFormula"))
        weight = _text(props.get("MolecularWeight"))
        iupac = _text(props.get("IUPACName"))
        smiles = _text(
            props.get("CanonicalSMILES") or props.get("ConnectivitySMILES"),
        )
        inchikey = _text(props.get("InChIKey"))

        parts: list[str] = []
        if formula:
            parts.append(f"Formula: {formula}")
        if weight:
            parts.append(f"MW: {weight}")
        if iupac:
            parts.append(f"IUPAC: {iupac}")
        if smiles:
            parts.append(f"SMILES: {smiles}")
        if inchikey:
            parts.append(f"InChIKey: {inchikey}")

        return SearchResult(
            title=title,
            url=_RECORD_URL.format(cid=cid),
            snippet=" | ".join(parts)[:MAX_SNIPPET_LENGTH],
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            extra={
                "cid": cid,
                "molecular_formula": formula,
                "molecular_weight": weight,
                "iupac_name": iupac,
                "canonical_smiles": smiles,
                "inchikey": inchikey,
            },
        )

    def _suggestion_result(self, name: str, rank: int) -> SearchResult:
        """Build a lightweight result for an autocomplete compound name."""
        return SearchResult(
            title=name,
            url=_SEARCH_URL.format(name=quote(name)),
            snippet="Compound name suggestion from PubChem.",
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            extra={"suggestion": True},
        )

    async def _fetch_properties(
        self,
        client: httpx.AsyncClient,
        url: str,
        limit: int,
    ) -> list[SearchResult]:
        """Fetch and parse compound property records, tolerating no-match."""
        resp = await client.get(url)
        if resp.status_code in (400, 404):
            # PubChem reports an unmatched compound name as a 404 (or 400 for
            # a malformed name), which is not an error for a search provider.
            return []
        resp.raise_for_status()

        results: list[SearchResult] = []
        for props in self._property_records(resp.json()):
            record = self._record(props, len(results) + 1)
            if record is not None:
                results.append(record)
            if len(results) >= limit:
                break
        return results

    async def _fetch_suggestions(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> list[str]:
        """Fetch related compound names from the autocomplete endpoint."""
        resp = await client.get(url, params={"limit": _MAX_SUGGESTIONS})
        if resp.status_code != 200:
            return []
        return self._suggestion_names(resp.json())

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search PubChem for chemical compounds matching *query*."""
        limit = min(params.num_results, self._max_results)
        if not query.strip() or limit < 1:
            return ProviderResult(results=[])

        name = _encode(query)
        property_url = _PROPERTY_URL.format(name=name, props=_PROPERTIES)
        autocomplete_url = _AUTOCOMPLETE_URL.format(name=name)

        async with self._client() as client:
            results, suggestions = await asyncio.gather(
                self._fetch_properties(client, property_url, limit),
                self._fetch_suggestions(client, autocomplete_url),
            )

        if not results:
            # No exact compound name matched: surface the autocomplete names as
            # lightweight results so an approximate query is still actionable.
            results = [
                self._suggestion_result(suggestion, rank)
                for rank, suggestion in enumerate(suggestions[:limit], start=1)
            ]
            suggestions = []

        # Drop suggestions already shown as matched compounds.
        matched = {result.title.casefold() for result in results}
        suggestions = [
            suggestion
            for suggestion in suggestions
            if suggestion.casefold() not in matched
        ]
        return ProviderResult(results=results, suggestions=suggestions)
