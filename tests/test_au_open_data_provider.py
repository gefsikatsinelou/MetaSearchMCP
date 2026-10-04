"""Unit tests for the Australian open data portal (data.gov.au) provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.au_open_data import AuOpenDataProvider

_SEARCH_URL = "https://data.gov.au/data/api/3/action/package_search"

_PAYLOAD = {
    "success": True,
    "result": {
        "count": 9983,
        "results": [
            {
                "title": "NSW Population Forecasts",
                "name": "nsw-population-forecasts",
                "notes": (
                    "Population forecasts for the Sydney Greater Metropolitan Area."
                ),
                "author": "Bureau of Transport Statistics",
                "id": "893b33ed-7fe3-4ea3-8a7c-e1cd0823fb06",
                "organization": {
                    "title": "Transport for NSW",
                    "name": "transport-for-nsw",
                },
                "tags": [
                    {"name": "population"},
                    {"name": "population"},
                    {"name": "transport"},
                ],
                "resources": [
                    {"format": "CSV"},
                    {"format": "GeoJSON"},
                    {"format": "CSV"},
                ],
                "license_title": "Creative Commons Attribution 3.0 Australia",
                "isopen": False,
                "num_resources": 2,
                "metadata_modified": "2025-06-24T08:19:00.460603",
            },
            {
                "title": "Bare Dataset",
                "name": "bare-dataset",
                "organization": "Some String Org",
                "author": None,
                "tags": "not-a-list",
                "resources": None,
                "metadata_modified": None,
            },
            {"title": "No slug here", "notes": "skipped: missing name"},
            {"name": "no-title", "id": "no-title"},
            "not-a-mapping",
        ],
    },
}


def _mock(respx_mock, payload: object = _PAYLOAD):
    """Mock the CKAN package_search endpoint with *payload*."""
    return respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=payload),
    )


def _provider() -> AuOpenDataProvider:
    """Return a fresh provider instance for each test."""
    return AuOpenDataProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "au_open_data"
    assert p.tags == ["web", "gov", "data", "knowledge"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "au_open_data" in registry
    assert registry["au_open_data"].tags == ["web", "gov", "data", "knowledge"]


@pytest.mark.asyncio
async def test_search_builds_structured_result(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("population", SearchParams(num_results=10))
    dataset = result.results[0]

    assert dataset.title == "NSW Population Forecasts"
    assert dataset.url == "https://data.gov.au/dataset/nsw-population-forecasts"
    assert dataset.source == "data.gov.au"
    assert dataset.provider == "au_open_data"
    assert dataset.rank == 1
    assert dataset.published_date == "2025-06-24"
    assert dataset.snippet == (
        "Population forecasts for the Sydney Greater Metropolitan Area. | "
        "Organization: Transport for NSW | "
        "Author: Bureau of Transport Statistics | "
        "Tags: population, transport | "
        "Formats: CSV, GeoJSON | "
        "Resources: 2 | "
        "License: Creative Commons Attribution 3.0 Australia"
    )
    assert dataset.extra == {
        "id": "893b33ed-7fe3-4ea3-8a7c-e1cd0823fb06",
        "name": "nsw-population-forecasts",
        "organization": "Transport for NSW",
        "author": "Bureau of Transport Statistics",
        "tags": ["population", "transport"],
        "formats": ["CSV", "GeoJSON"],
        "resources": 2,
        "license": "Creative Commons Attribution 3.0 Australia",
        "is_open": False,
        "updated": "2025-06-24",
    }


@pytest.mark.asyncio
async def test_search_accepts_string_organization_and_missing_metadata(
    respx_mock,
) -> None:
    _mock(respx_mock)

    result = await _provider().search("population", SearchParams(num_results=10))
    bare = result.results[1]

    assert bare.title == "Bare Dataset"
    assert bare.url == "https://data.gov.au/dataset/bare-dataset"
    assert bare.rank == 2
    # No description, so the snippet leads with the organization.
    assert bare.snippet == "Organization: Some String Org"
    assert bare.published_date is None
    assert bare.extra["organization"] == "Some String Org"
    assert bare.extra["author"] is None
    assert bare.extra["tags"] == []
    assert bare.extra["formats"] == []
    assert bare.extra["resources"] == 0
    assert bare.extra["license"] is None
    assert bare.extra["is_open"] is False
    assert bare.extra["updated"] is None


@pytest.mark.asyncio
async def test_search_skips_incomplete_and_malformed_entries(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("population", SearchParams(num_results=10))

    assert [r.title for r in result.results] == [
        "NSW Population Forecasts",
        "Bare Dataset",
    ]
    assert [r.rank for r in result.results] == [1, 2]


@pytest.mark.asyncio
async def test_search_deduplicates_by_id(respx_mock) -> None:
    duplicate = {
        "title": "Same dataset",
        "name": "same-dataset",
        "id": "abc",
        "organization": {"title": "Org"},
    }
    _mock(
        respx_mock,
        {"success": True, "result": {"results": [duplicate, dict(duplicate)]}},
    )

    result = await _provider().search("same", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["Same dataset"]


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("population", SearchParams(num_results=1))

    assert [r.title for r in result.results] == ["NSW Population Forecasts"]


@pytest.mark.asyncio
async def test_search_sends_query_params(respx_mock) -> None:
    route = _mock(respx_mock)

    await _provider().search("renewable energy", SearchParams(num_results=7))

    params = route.calls.last.request.url.params
    assert params["q"] == "renewable energy"
    assert params["rows"] == "7"


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
        {"result": None},
        {"result": {"results": None}},
        {"result": {"results": "nope"}},
    ):
        respx_mock.get(_SEARCH_URL).mock(
            return_value=respx.MockResponse(200, json=payload),
        )
        result = await _provider().search("population", SearchParams(num_results=5))
        assert result.results == []


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("population", SearchParams(num_results=5))
