"""Unit tests for the Reactome pathway/molecule search provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.reactome import ReactomeProvider

_SEARCH_URL = "https://reactome.org/ContentService/search/query"

_PAYLOAD = {
    "rowCount": 4,
    "numberOfGroups": 2,
    "numberOfMatches": 4,
    "results": [
        {
            "typeName": "Pathway",
            "entriesCount": 2,
            "rowCount": 2,
            "entries": [
                {
                    "dbId": "70171",
                    "stId": "R-HSA-70171",
                    "id": "R-HSA-70171",
                    "name": '<span class="highlighting" >Glycolysis</span>',
                    "type": "Pathway",
                    "exactType": "Pathway",
                    "species": ["Homo sapiens"],
                    "summation": (
                        "The reactions of "
                        '<span class="highlighting" >glycolysis</span> '
                        "convert glucose 6-phosphate to pyruvate."
                    ),
                    "compartmentNames": ["cytosol"],
                    "isDisease": False,
                    "databaseName": "Reactome",
                    "referenceURL": None,
                },
                {"name": "Skipped: no stable id"},
            ],
        },
        {
            "typeName": "Protein",
            "entriesCount": 2,
            "rowCount": 2,
            "entries": [
                {
                    "dbId": "69488",
                    "stId": "R-HSA-69488",
                    "name": '<span class="highlighting" >TP53</span>',
                    "type": "Protein",
                    "exactType": "ReferenceGeneProduct",
                    "species": ["Homo sapiens"],
                    "referenceName": "TP53",
                    "referenceIdentifier": "P04637",
                    "compartmentNames": ["nucleoplasm"],
                    "isDisease": False,
                    "databaseName": "UniProt",
                    "referenceURL": "http://purl.uniprot.org/uniprot/P04637",
                },
                "not-a-mapping",
            ],
        },
    ],
}


def _mock(respx_mock, payload: object = _PAYLOAD):
    """Mock the Reactome search endpoint with *payload*."""
    return respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=payload),
    )


def _provider() -> ReactomeProvider:
    """Return a fresh provider instance for each test."""
    return ReactomeProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "reactome"
    assert p.tags == ["academic", "web", "bio", "science"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "reactome" in registry
    assert registry["reactome"].tags == ["academic", "web", "bio", "science"]


@pytest.mark.asyncio
async def test_search_builds_structured_result(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("glycolysis", SearchParams(num_results=10))
    first = result.results[0]

    assert first.title == "Glycolysis"
    assert first.url == "https://reactome.org/content/detail/R-HSA-70171"
    assert first.source == "reactome.org"
    assert first.provider == "reactome"
    assert first.rank == 1
    assert first.snippet == (
        "The reactions of glycolysis convert glucose 6-phosphate to pyruvate. | "
        "Type: Pathway | Species: Homo sapiens | Compartment: cytosol"
    )
    assert first.extra == {
        "id": "R-HSA-70171",
        "db_id": "70171",
        "type": "Pathway",
        "exact_type": "Pathway",
        "species": ["Homo sapiens"],
        "compartments": ["cytosol"],
        "reference_name": None,
        "reference_identifier": None,
        "database": "Reactome",
        "reference_url": None,
        "is_disease": False,
    }

    second = result.results[1]
    assert second.title == "TP53"
    assert second.url == "https://reactome.org/content/detail/R-HSA-69488"
    assert second.snippet == (
        "Type: Protein | Species: Homo sapiens | Compartment: nucleoplasm"
    )
    assert second.extra["reference_name"] == "TP53"
    assert second.extra["reference_identifier"] == "P04637"
    assert second.extra["database"] == "UniProt"
    assert second.extra["reference_url"] == ("http://purl.uniprot.org/uniprot/P04637")


@pytest.mark.asyncio
async def test_search_strips_highlighting_markup(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("glycolysis", SearchParams(num_results=10))

    for record in result.results:
        assert "<span" not in record.title
        assert "<span" not in record.snippet
        assert "highlighting" not in record.title


@pytest.mark.asyncio
async def test_search_degrades_on_missing_fields(respx_mock) -> None:
    _mock(
        respx_mock,
        {"results": [{"entries": [{"stId": "R-X-1", "name": "Minimal"}]}]},
    )

    result = await _provider().search("minimal", SearchParams(num_results=5))
    only = result.results[0]

    assert only.url == "https://reactome.org/content/detail/R-X-1"
    assert only.snippet == ""
    assert only.extra["db_id"] is None
    assert only.extra["type"] is None
    assert only.extra["exact_type"] is None
    assert only.extra["species"] == []
    assert only.extra["compartments"] == []
    assert only.extra["reference_name"] is None
    assert only.extra["database"] is None
    assert only.extra["is_disease"] is False


@pytest.mark.asyncio
async def test_search_skips_incomplete_and_malformed_entries(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("glycolysis", SearchParams(num_results=10))

    assert [r.title for r in result.results] == ["Glycolysis", "TP53"]
    assert [r.rank for r in result.results] == [1, 2]


@pytest.mark.asyncio
async def test_search_deduplicates_by_stable_id(respx_mock) -> None:
    duplicate = {"stId": "R-HSA-1", "name": "Same record"}
    _mock(
        respx_mock,
        {"results": [{"entries": [dict(duplicate)]}, {"entries": [dict(duplicate)]}]},
    )

    result = await _provider().search("same", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["Same record"]


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("glycolysis", SearchParams(num_results=1))

    assert [r.title for r in result.results] == ["Glycolysis"]


@pytest.mark.asyncio
async def test_search_sends_query_params(respx_mock) -> None:
    route = _mock(respx_mock)

    await _provider().search("glycolysis", SearchParams(num_results=7))

    params = route.calls.last.request.url.params
    assert params["query"] == "glycolysis"
    assert params["cluster"] == "true"


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    route = _mock(respx_mock)

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_handles_unexpected_payload_shapes(respx_mock) -> None:
    for payload in (
        ["not", "a", "mapping"],
        {},
        {"results": None},
        {"results": "nope"},
        {"results": [{"entries": None}]},
        {"results": ["not-a-group"]},
    ):
        respx_mock.get(_SEARCH_URL).mock(
            return_value=respx.MockResponse(200, json=payload),
        )
        result = await _provider().search("glycolysis", SearchParams(num_results=5))
        assert result.results == []


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("glycolysis", SearchParams(num_results=5))
