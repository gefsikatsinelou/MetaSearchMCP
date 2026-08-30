"""Unit tests for the ChEMBL drug/bioactive molecule search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.chembl import ChEMBLProvider

_SAMPLE_ITEM = {
    "molecule_chembl_id": "CHEMBL25",
    "pref_name": "ASPIRIN",
    "max_phase": 4.0,
    "first_approval": 1950,
    "withdrawn_flag": False,
    "atc_classifications": ["B01AC06", "N02BA01"],
    "molecule_structures": {
        "canonical_smiles": "CC(=O)Oc1ccccc1C(=O)O",
    },
    "molecule_properties": {
        "full_molformula": "C9H8O4",
        "full_mwt": "180.16",
        "alogp": "1.31",
        "hba": 3,
        "hbd": 1,
        "num_ro5_violations": 0,
    },
    "molecule_synonyms": [
        {"molecule_synonym": "Acetosalic acid", "syn_type": "TRADE_NAME"},
        {"molecule_synonym": "8-hour bayer", "syn_type": "TRADE_NAME"},
        {"molecule_synonym": "Acetylsalicylic acid", "syn_type": "ATC"},
    ],
}

_SAMPLE_RESPONSE: dict[str, object] = {
    "molecules": [
        _SAMPLE_ITEM,
        {
            # Missing pref_name -> skipped.
            "molecule_chembl_id": "CHEMBL999",
        },
        {
            "molecule_chembl_id": "CHEMBL123",
            "pref_name": "IBUPROFEN",
            "max_phase": None,
            "first_approval": None,
            "withdrawn_flag": True,
            "atc_classifications": None,
            "molecule_structures": None,
            "molecule_properties": None,
            "molecule_synonyms": None,
        },
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"molecules": []}


def _provider() -> ChEMBLProvider:
    return ChEMBLProvider()


def test_chembl_name_and_tags() -> None:
    p = _provider()
    assert p.name == "chembl"
    assert p.tags == ["drugs", "pharma", "academic", "web"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "ASPIRIN"
    assert r.url == "https://www.ebi.ac.uk/chembl/report_card/CHEMBL25/"
    assert "Formula: C9H8O4" in r.snippet
    assert "MW: 180.16" in r.snippet
    assert "ATC: B01AC06, N02BA01" in r.snippet
    assert r.provider == "chembl"
    assert r.source == "ebi.ac.uk/chembl"
    assert r.rank == 1
    assert r.published_date == "1950"
    assert r.extra["chembl_id"] == "CHEMBL25"
    assert r.extra["molecular_formula"] == "C9H8O4"
    assert r.extra["canonical_smiles"] == "CC(=O)Oc1ccccc1C(=O)O"
    assert r.extra["atc_codes"] == ["B01AC06", "N02BA01"]
    assert r.extra["max_phase"] == "4.0"
    assert r.extra["withdrawn"] is False
    assert "Acetosalic acid" in r.extra["trade_names"]


def test_parse_sparse_item() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    r = result.results[1]
    assert r.title == "IBUPROFEN"
    assert r.snippet == ""
    assert r.published_date is None
    assert r.extra["atc_codes"] == []
    assert r.extra["max_phase"] == ""
    assert r.extra["withdrawn"] is True


def test_parse_skips_items_missing_name_or_id() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert all(r.title and r.extra["chembl_id"] for r in result.results)


def test_parse_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1
    assert result.results[0].title == "ASPIRIN"


def test_parse_empty_and_malformed() -> None:
    assert _provider()._parse(_EMPTY_RESPONSE).results == []
    assert _provider()._parse({}).results == []
    assert _provider()._parse({"molecules": ["not-a-dict", None, 42]}).results == []
    assert _provider()._parse("junk").results == []


def test_properties_guards_against_junk() -> None:
    assert ChEMBLProvider._properties({"molecule_properties": "junk"}) == {}
    assert ChEMBLProvider._properties({}) == {}


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/search.json").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("aspirin", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "chembl"
    request = respx_mock.calls.last.request
    assert request.url.params["q"] == "aspirin"
    assert request.url.params["limit"] == "5"


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/search.json").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("zzzz", SearchParams(num_results=5))
    assert result.results == []
