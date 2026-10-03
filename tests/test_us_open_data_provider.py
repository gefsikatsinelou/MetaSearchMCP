"""Unit tests for the U.S. federal open data catalog provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.us_open_data import UsOpenDataProvider

_SEARCH_URL = "https://catalog.data.gov/search"

_PAYLOAD = {
    "sort": "relevance",
    "after": "cursor==",
    "results": [
        {
            "title": "Air Quality Maintenance Area Ozone",
            "description": "Air quality maintenance areas for ozone in Oregon.",
            "slug": "air-quality-maintenance-area-ozone",
            "identifier": (
                "https://www.arcgis.com/home/item.html?id=68ff05&sublayer=0"
            ),
            "organization": {
                "id": "0af4eecd",
                "name": "State of Oregon",
                "organization_type": "State Government",
            },
            "publisher": "Oregon Department of Environmental Quality.",
            "keyword": [
                "air quality",
                "deq",
                "oregon",
                "ozone",
                "air quality",
                "geospatial",
            ],
            "theme": ["geospatial", "environment", "health", "extra"],
            "distribution_titles": ["CSV", "Excel", "GeoJSON", "KML", "Shapefile"],
            "last_harvested_date": "2026-09-10T18:40:52.684563",
            "popularity": 9,
            "access_level": "public",
            "has_download": True,
            "has_spatial": True,
            "type": "dataset",
        },
        {
            "title": "Renewable Energy Consumption",
            "identifier": "https://example.gov/datasets/renewable-energy",
            "organization": "Some String Org",
            "publisher": None,
            "keyword": "not-a-list",
            "theme": None,
            "distribution_titles": [],
            "last_harvested_date": None,
            "popularity": 0,
            "dcat": {"description": "DCAT fallback description."},
        },
        {"title": "No location", "description": "Skipped: no slug or identifier"},
        {"slug": "no-title", "identifier": "https://example.gov/no-title"},
        "not-a-mapping",
    ],
}


def _mock(respx_mock, payload: object = _PAYLOAD):
    """Mock the catalog search endpoint with *payload*."""
    return respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=payload),
    )


def _provider() -> UsOpenDataProvider:
    """Return a fresh provider instance for each test."""
    return UsOpenDataProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "us_open_data"
    assert p.tags == ["web", "gov", "data", "knowledge"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "us_open_data" in registry
    assert registry["us_open_data"].tags == ["web", "gov", "data", "knowledge"]


@pytest.mark.asyncio
async def test_search_builds_structured_result(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("air quality", SearchParams(num_results=10))
    dataset = result.results[0]

    assert dataset.title == "Air Quality Maintenance Area Ozone"
    assert dataset.url == (
        "https://catalog.data.gov/dataset/air-quality-maintenance-area-ozone"
    )
    assert dataset.source == "catalog.data.gov"
    assert dataset.provider == "us_open_data"
    assert dataset.rank == 1
    assert dataset.published_date == "2026-09-10"
    assert dataset.snippet == (
        "Air quality maintenance areas for ozone in Oregon. | "
        "Publisher: Oregon Department of Environmental Quality. | "
        "Organization: State of Oregon | "
        "Keywords: air quality, deq, oregon, ozone, geospatial | "
        "Themes: geospatial, environment, health | "
        "Formats: CSV, Excel, GeoJSON, KML | Popularity: 9"
    )
    assert dataset.extra == {
        "id": "https://www.arcgis.com/home/item.html?id=68ff05&sublayer=0",
        "slug": "air-quality-maintenance-area-ozone",
        "organization": "State of Oregon",
        "publisher": "Oregon Department of Environmental Quality.",
        "keywords": ["air quality", "deq", "oregon", "ozone", "geospatial"],
        "themes": ["geospatial", "environment", "health"],
        "formats": ["CSV", "Excel", "GeoJSON", "KML"],
        "popularity": 9,
        "access_level": "public",
        "has_download": True,
        "has_spatial": True,
        "updated": "2026-09-10",
    }


@pytest.mark.asyncio
async def test_search_falls_back_to_identifier_and_dcat(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("energy", SearchParams(num_results=10))
    second = result.results[1]

    # No slug, so the bare identifier URL is used directly.
    assert second.url == "https://example.gov/datasets/renewable-energy"
    assert second.rank == 2
    # A string organization is accepted; malformed lists degrade to empty.
    assert second.extra["organization"] == "Some String Org"
    assert second.extra["publisher"] is None
    assert second.extra["keywords"] == []
    assert second.extra["themes"] == []
    assert second.extra["formats"] == []
    # The DCAT description is used when the top-level one is absent.
    assert second.snippet == (
        "DCAT fallback description. | Organization: Some String Org"
    )
    assert second.published_date is None


@pytest.mark.asyncio
async def test_search_skips_incomplete_and_malformed_entries(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("energy", SearchParams(num_results=10))

    assert [r.title for r in result.results] == [
        "Air Quality Maintenance Area Ozone",
        "Renewable Energy Consumption",
    ]
    assert [r.rank for r in result.results] == [1, 2]


@pytest.mark.asyncio
async def test_search_deduplicates_by_identifier(respx_mock) -> None:
    duplicate = {
        "title": "Same dataset",
        "identifier": "https://example.gov/datasets/same",
    }
    _mock(respx_mock, {"results": [duplicate, dict(duplicate)]})

    result = await _provider().search("same", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["Same dataset"]


@pytest.mark.asyncio
async def test_search_returns_result_without_extra_metadata(respx_mock) -> None:
    _mock(
        respx_mock,
        {
            "results": [
                {"title": "Bare dataset", "slug": "bare-dataset"},
            ],
        },
    )

    result = await _provider().search("bare", SearchParams(num_results=5))
    dataset = result.results[0]

    assert dataset.url == "https://catalog.data.gov/dataset/bare-dataset"
    assert dataset.snippet == ""
    assert dataset.published_date is None
    assert dataset.extra["organization"] is None
    assert dataset.extra["popularity"] == 0


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("air", SearchParams(num_results=1))

    assert [r.title for r in result.results] == [
        "Air Quality Maintenance Area Ozone",
    ]


@pytest.mark.asyncio
async def test_search_sends_query_params(respx_mock) -> None:
    route = _mock(respx_mock)

    await _provider().search("renewable energy", SearchParams(num_results=7))

    params = route.calls.last.request.url.params
    assert params["q"] == "renewable energy"
    assert params["per_page"] == "7"


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
    ):
        respx_mock.get(_SEARCH_URL).mock(
            return_value=respx.MockResponse(200, json=payload),
        )
        result = await _provider().search("air", SearchParams(num_results=5))
        assert result.results == []


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("air", SearchParams(num_results=5))
