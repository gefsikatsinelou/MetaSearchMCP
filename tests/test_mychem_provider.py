"""Unit tests for the MyChem.info chemical/drug search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.mychem import MyChemProvider

_SAMPLE_RESPONSE: dict[str, object] = {
    "took": 12,
    "total": 240,
    "max_score": 28.8,
    "hits": [
        {
            "_id": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
            "_score": 28.8,
            "chebi": {
                "id": "CHEBI:15365",
                "name": "acetylsalicylic acid",
                "formula": "C9H8O4",
                "mass": 180.157,
                "definition": "An acetyl derivative of salicylic acid.",
            },
            "chembl": {
                "pref_name": "ASPIRIN",
                "molecule_chembl_id": "CHEMBL25",
                "max_phase": 4.0,
                "first_approval": 1950,
                "molecule_type": "Small molecule",
                "withdrawn_flag": False,
                "smiles": "CC(=O)Oc1ccccc1C(=O)O",
            },
            "drugbank": {"id": "DB00945", "name": "Acetylsalicylic acid"},
            "pubchem": {"cid": 2244, "molecular_weight": 180.16, "xlogp": 1.2},
            "unii": {
                "display_name": "ASPIRIN",
                "inchikey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
                "molecular_formula": "C9H8O4",
                "smiles": "CC(=O)OC1=CC=CC=C1C(=O)O",
                "registry_number": "50-78-2",
                "rxcui": "1191",
                "pubchem": 2244,
                "unii": "R16CO5Y76E",
                "substance_type": "chemical",
                "ncit": "C287",
                "ncit_description": "An orally administered non-steroidal agent.",
            },
        },
        {
            # unii arrives as a list; no ChEMBL record -> DrugBank name wins.
            "_id": "XZWYZXLIPXDOLR-UHFFFAOYSA-N",
            "chebi": {"id": "CHEBI:6801", "name": "metformin", "formula": "C4H11N5"},
            "drugbank": {"id": "DB00331", "name": "Metformin"},
            "pubchem": {"cid": 4091, "molecular_weight": 129.16},
            "unii": [
                {"display_name": "METFORMIN", "rcui": "6809"},
                {"display_name": "METFORMIN HYDROCHLORIDE", "rxcui": "235425"},
            ],
        },
        {
            # Withdrawn drug, no identifiers beyond the InChIKey.
            "_id": "RZJQGNCSTQAWON-UHFFFAOYSA-N",
            "chembl": {"pref_name": "ROFECOXIB", "withdrawn_flag": True},
        },
        {
            # No name in any source -> the InChIKey is used as the title.
            "_id": "ZKHQWZAMYRWXGA-KQYNXXCUSA-N",
            "pubchem": {"cid": 5957},
        },
        "junk",
        None,
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"took": 1, "total": 0, "hits": []}

# Two records for the same InChIKey plus an unrelated substance.
_DEDUP_HITS: list[object] = [
    {
        "_id": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
        "chembl": {"pref_name": "ASPIRIN", "molecule_chembl_id": "CHEMBL25"},
    },
    {"_id": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N", "chebi": {"name": "acetylsalicylic acid"}},
    {"_id": "XZWYZXLIPXDOLR-UHFFFAOYSA-N", "drugbank": {"name": "Metformin"}},
]


def _provider() -> MyChemProvider:
    return MyChemProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "mychem"
    assert p.tags == ["drugs", "chemistry", "bio", "academic", "web"]
    assert p.is_available() is True


def test_parse_basic_fields() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 4
    r = result.results[0]
    assert r.title == "ASPIRIN"
    assert r.url == "https://pubchem.ncbi.nlm.nih.gov/compound/2244"
    assert r.provider == "mychem"
    assert r.source == "mychem.info"
    assert r.rank == 1
    assert "Formula: C9H8O4" in r.snippet
    assert "MW: 180.16" in r.snippet
    assert "CAS: 50-78-2" in r.snippet
    assert "Max phase: 4 (first approved 1950)" in r.snippet
    assert "SMILES: CC(=O)OC1=CC=CC=C1C(=O)O" in r.snippet
    assert "ChEMBL CHEMBL25" in r.snippet
    assert "DrugBank DB00945" in r.snippet
    assert "UNII R16CO5Y76E" in r.snippet
    assert "non-steroidal" in r.snippet
    assert "Sources: chembl, drugbank, chebi, unii, pubchem" in r.snippet
    assert r.extra["inchikey"] == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
    assert r.extra["chembl_id"] == "CHEMBL25"
    assert r.extra["pubchem_cid"] == 2244
    assert r.extra["rxcui"] == "1191"
    assert r.extra["molecular_weight"] == 180.16
    assert r.extra["max_phase"] == 4.0
    assert r.extra["first_approval"] == 1950
    assert r.extra["withdrawn"] is False
    assert r.extra["molecule_type"] == "Small molecule"
    assert r.extra["substance_type"] == "chemical"
    assert r.extra["ncit"] == "C287"
    assert r.extra["total_results"] == 240


def test_parse_list_unii_and_name_fallbacks() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    r = result.results[1]

    assert r.title == "Metformin"
    assert r.url == "https://pubchem.ncbi.nlm.nih.gov/compound/4091"
    assert r.rank == 2
    # Formula falls back to ChEBI (no UNII molecular formula here).
    assert "Formula: C4H11N5" in r.snippet
    assert "MW: 129.16" in r.snippet
    assert r.extra["drugbank_id"] == "DB00331"
    assert r.extra["chebi_id"] == "CHEBI:6801"
    assert "Sources: drugbank, chebi, unii, pubchem" in r.snippet


def test_parse_withdrawn_and_identifier_only_hits() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    withdrawn = result.results[2]
    assert withdrawn.title == "ROFECOXIB"
    assert withdrawn.extra["withdrawn"] is True
    assert "Withdrawn" in withdrawn.snippet
    # No PubChem/ChEMBL identifiers -> the MyChem.info substance page is used.
    assert withdrawn.url == "https://mychem.info/v1/chem/RZJQGNCSTQAWON-UHFFFAOYSA-N"

    unnamed = result.results[3]
    assert unnamed.title == "ZKHQWZAMYRWXGA-KQYNXXCUSA-N"
    assert unnamed.url == "https://pubchem.ncbi.nlm.nih.gov/compound/5957"
    assert unnamed.extra["name"] is None


def test_parse_deduplicates_by_inchikey() -> None:
    data = {"hits": _DEDUP_HITS, "total": 3}

    results = _provider()._parse(data).results
    assert [r.title for r in results] == ["ASPIRIN", "Metformin"]
    assert [r.rank for r in results] == [1, 2]


def test_parse_respects_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=2)
    assert len(result.results) == 2
    assert result.results[1].title == "Metformin"


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse({}).results == []
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({"hits": "nope"}).results == []
    assert p._parse({"hits": [42, None]}).results == []
    assert p._parse("junk").results == []


def test_numeric_coercion_helpers() -> None:
    from metasearchmcp.providers.mychem import _as_float, _as_int

    assert _as_int(2244) == 2244
    assert _as_int("2244") == 2244
    assert _as_int(4.0) == 4
    assert _as_int("nope") is None
    assert _as_int(True) is None
    assert _as_float("180.16") == 180.16
    assert _as_float(None) is None


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get("https://mychem.info/v1/query").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    result = await _provider().search("aspirin", SearchParams(num_results=5))

    assert len(result.results) == 4
    assert result.results[0].provider == "mychem"
    assert len(respx_mock.calls) == 1
    request = respx_mock.calls[0].request
    assert request.url.params["q"] == "aspirin"
    assert request.url.params["size"] == "5"
    assert "chembl.pref_name" in request.url.params["fields"]


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    import respx

    respx_mock.get("https://mychem.info/v1/query").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    result = await _provider().search("   ", SearchParams(num_results=5))
    assert result.results == []
    assert len(respx_mock.calls) == 0


@pytest.mark.asyncio
async def test_search_no_match(respx_mock) -> None:
    import respx

    respx_mock.get("https://mychem.info/v1/query").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    result = await _provider().search("zzzz", SearchParams(num_results=5))
    assert result.results == []


def test_registry_includes_mychem() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "mychem" in registry
    assert registry["mychem"].tags == ["drugs", "chemistry", "bio", "academic", "web"]
