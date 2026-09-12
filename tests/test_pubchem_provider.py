"""Unit tests for the PubChem compound search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.pubchem import PubChemProvider, _encode, _text

_PROPERTY_RESPONSE: dict[str, object] = {
    "PropertyTable": {
        "Properties": [
            {
                "CID": 2244,
                "MolecularFormula": "C9H8O4",
                "MolecularWeight": "180.16",
                "ConnectivitySMILES": "CC(=O)OC1=CC=CC=C1C(=O)O",
                "InChIKey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
                "IUPACName": "2-acetyloxybenzoic acid",
                "Title": "Aspirin",
            },
            {
                # Numeric weight; no IUPAC/SMILES; padded title.
                "CID": 5793,
                "MolecularFormula": "C6H12O6",
                "MolecularWeight": 180.16,
                "Title": "  D-Glucose  ",
            },
            # Missing CID -> skipped.
            {"Title": "No CID"},
            # Missing title -> skipped.
            {"CID": 999},
            "junk",
        ]
    }
}

_AUTOCOMPLETE_RESPONSE: dict[str, object] = {
    "status": {"code": 0},
    "total": 4,
    "dictionary_terms": {
        "compound": [
            "aspirin",
            "NO-aspirin",
            "Aspirin DL-lysine",
            "Aspirin aluminum",
        ]
    },
}

_EMPTY_PROPERTY_RESPONSE: dict[str, object] = {
    "Fault": {"Code": "PUGREST.NotFound", "Message": "No CID found"},
}

_PROPERTY_ROUTE = r".*/pug/compound/name/.*/property/.*/JSON"
_AUTOCOMPLETE_ROUTE = r".*/autocomplete/compound/.*/json"


def _provider() -> PubChemProvider:
    return PubChemProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "pubchem"
    assert p.tags == ["chemistry", "science", "bio", "web"]
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "pubchem" in registry
    assert registry["pubchem"].tags == ["chemistry", "science", "bio", "web"]


def test_helpers() -> None:
    assert _text(None) == ""
    assert _text(180.16) == "180.16"
    assert _text("  a\n b ") == "a b"
    assert _encode("acetylsalicylic acid") == "acetylsalicylic%20acid"
    assert _encode("  1,3-x  ") == "1%2C3-x"


def test_property_records_extraction() -> None:
    p = _provider()
    records = p._property_records(_PROPERTY_RESPONSE)
    assert len(records) == 4
    assert records[0]["CID"] == 2244
    assert p._property_records({}) == []
    assert p._property_records({"PropertyTable": "nope"}) == []
    assert p._property_records({"PropertyTable": {"Properties": "nope"}}) == []
    assert p._property_records("junk") == []


def test_suggestion_names_extraction() -> None:
    p = _provider()
    assert p._suggestion_names(_AUTOCOMPLETE_RESPONSE) == [
        "aspirin",
        "NO-aspirin",
        "Aspirin DL-lysine",
        "Aspirin aluminum",
    ]
    assert p._suggestion_names({}) == []
    assert p._suggestion_names({"dictionary_terms": "nope"}) == []
    assert p._suggestion_names({"dictionary_terms": {"compound": "nope"}}) == []
    assert p._suggestion_names("junk") == []


def test_record_builds_result() -> None:
    record = _provider()._record(
        {
            "CID": 2244,
            "MolecularFormula": "C9H8O4",
            "MolecularWeight": "180.16",
            "ConnectivitySMILES": "CC(=O)OC1=CC=CC=C1C(=O)O",
            "InChIKey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
            "IUPACName": "2-acetyloxybenzoic acid",
            "Title": "Aspirin",
        },
        rank=1,
    )

    assert record is not None
    assert record.title == "Aspirin"
    assert record.url == "https://pubchem.ncbi.nlm.nih.gov/compound/2244"
    assert record.provider == "pubchem"
    assert record.source == "pubchem.ncbi.nlm.nih.gov"
    assert record.rank == 1
    assert "Formula: C9H8O4" in record.snippet
    assert "MW: 180.16" in record.snippet
    assert "IUPAC: 2-acetyloxybenzoic acid" in record.snippet
    assert "SMILES: CC(=O)OC1=CC=CC=C1C(=O)O" in record.snippet
    assert record.extra["cid"] == 2244
    assert record.extra["inchikey"] == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"


def test_record_prefers_canonical_smiles() -> None:
    record = _provider()._record(
        {
            "CID": 1,
            "Title": "X",
            "CanonicalSMILES": "C",
            "ConnectivitySMILES": "IGNORED",
        },
        rank=1,
    )
    assert record is not None
    assert record.extra["canonical_smiles"] == "C"


def test_record_rejects_incomplete_entries() -> None:
    p = _provider()
    assert p._record({"Title": "No CID"}, rank=1) is None
    assert p._record({"CID": 1}, rank=1) is None
    assert p._record({"CID": "1", "Title": "string cid"}, rank=1) is None


@pytest.mark.asyncio
async def test_search_returns_records_and_suggestions(respx_mock) -> None:
    import respx

    respx_mock.get(url__regex=_PROPERTY_ROUTE).mock(
        return_value=respx.MockResponse(200, json=_PROPERTY_RESPONSE),
    )
    respx_mock.get(url__regex=_AUTOCOMPLETE_ROUTE).mock(
        return_value=respx.MockResponse(200, json=_AUTOCOMPLETE_RESPONSE),
    )

    result = await _provider().search("aspirin", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["Aspirin", "D-Glucose"]
    assert result.results[0].provider == "pubchem"
    assert result.results[1].rank == 2
    # "aspirin" duplicates the matched title and is filtered out.
    assert result.suggestions == [
        "NO-aspirin",
        "Aspirin DL-lysine",
        "Aspirin aluminum",
    ]

    auto_call = next(
        call for call in respx_mock.calls if "/autocomplete/" in str(call.request.url)
    )
    assert auto_call.request.url.params["limit"] == "8"
    prop_call = next(
        call for call in respx_mock.calls if "/property/" in str(call.request.url)
    )
    assert "CanonicalSMILES" in prop_call.request.url.path


@pytest.mark.asyncio
async def test_search_falls_back_to_suggestions_on_no_match(respx_mock) -> None:
    import respx

    respx_mock.get(url__regex=_PROPERTY_ROUTE).mock(
        return_value=respx.MockResponse(404, json=_EMPTY_PROPERTY_RESPONSE),
    )
    respx_mock.get(url__regex=_AUTOCOMPLETE_ROUTE).mock(
        return_value=respx.MockResponse(200, json=_AUTOCOMPLETE_RESPONSE),
    )

    result = await _provider().search("aspirin-ish", SearchParams(num_results=5))

    assert [r.title for r in result.results] == [
        "aspirin",
        "NO-aspirin",
        "Aspirin DL-lysine",
        "Aspirin aluminum",
    ]
    assert result.results[0].url.startswith(
        "https://pubchem.ncbi.nlm.nih.gov/#query=",
    )
    assert result.results[0].extra["suggestion"] is True
    assert result.suggestions == []


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    import respx

    respx_mock.get(url__regex=_PROPERTY_ROUTE).mock(
        return_value=respx.MockResponse(200, json=_PROPERTY_RESPONSE),
    )
    respx_mock.get(url__regex=_AUTOCOMPLETE_ROUTE).mock(
        return_value=respx.MockResponse(200, json=_AUTOCOMPLETE_RESPONSE),
    )

    result = await _provider().search("aspirin", SearchParams(num_results=1))
    assert len(result.results) == 1


@pytest.mark.asyncio
async def test_search_empty_query_short_circuits(respx_mock) -> None:
    result = await _provider().search("   ", SearchParams(num_results=5))
    assert result.results == []
    assert len(respx_mock.calls) == 0
