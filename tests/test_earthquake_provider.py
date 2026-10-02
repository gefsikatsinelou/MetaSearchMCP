"""Unit tests for the USGS Earthquake Catalog provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.earthquake import EarthquakeProvider

_API_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

_PAYLOAD = {
    "type": "FeatureCollection",
    "metadata": {"count": 2},
    "features": [
        {
            "type": "Feature",
            "properties": {
                "mag": 5.2,
                "place": "10 km SSW of Japan",
                "time": 1700000000000,
                "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000abcd",
                "tsunami": 1,
                "felt": 12,
                "alert": "yellow",
                "sig": 450,
            },
            "geometry": {"type": "Point", "coordinates": [142.1, 38.2, 30.5]},
        },
        {
            "type": "Feature",
            "properties": {
                "mag": None,
                "place": "Off the coast of California",
                "time": 1700003600000,
                "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000efgh",
                "tsunami": 0,
                "felt": 0,
                "alert": None,
                "sig": 10,
            },
            "geometry": {"type": "Point", "coordinates": [-124.4, 40.3, 8.0]},
        },
    ],
}


def _provider() -> EarthquakeProvider:
    """Return a fresh provider instance for each test."""
    return EarthquakeProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "earthquake"
    assert p.tags == ["science", "geo", "news"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "earthquake" in registry
    assert registry["earthquake"].tags == ["science", "geo", "news"]


@pytest.mark.asyncio
async def test_search_place_query_filters_and_builds_results(respx_mock) -> None:
    route = respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_PAYLOAD),
    )

    result = await _provider().search("japan", SearchParams(num_results=10))

    assert route.called
    # Only the event whose place contains "japan" is kept.
    assert [r.title for r in result.results] == ["M 5.2 - 10 km SSW of Japan"]

    request = route.calls.last.request
    assert request.url.params["format"] == "geojson"
    assert request.url.params["orderby"] == "time"
    assert request.url.params["limit"] == "500"
    assert "starttime" in request.url.params
    assert "minmagnitude" not in request.url.params

    first = result.results[0]
    assert first.url == "https://earthquake.usgs.gov/earthquakes/eventpage/us7000abcd"
    assert first.source == "earthquake.usgs.gov"
    assert first.provider == "earthquake"
    assert first.rank == 1
    assert first.published_date == "2023-11-14"
    assert first.snippet == (
        "2023-11-14 22:13:20 UTC | depth 30.5 km | tsunami advisory | "
        "12 felt reports | yellow alert level"
    )
    assert first.extra == {
        "magnitude": 5.2,
        "place": "10 km SSW of Japan",
        "depth_km": 30.5,
        "latitude": 38.2,
        "longitude": 142.1,
        "tsunami": 1,
        "felt_reports": 12,
        "alert": "yellow",
        "significance": 450,
    }


@pytest.mark.asyncio
async def test_search_numeric_query_uses_minmagnitude(respx_mock) -> None:
    route = respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_PAYLOAD),
    )

    result = await _provider().search("5", SearchParams(num_results=10))

    request = route.calls.last.request
    assert request.url.params["minmagnitude"] == "5"
    assert "starttime" not in request.url.params

    # A numeric query keeps every returned event (catalogue filtered already).
    assert len(result.results) == 2
    assert result.results[1].title == "Off the coast of California"
    assert result.results[1].published_date == "2023-11-14"
    assert result.results[1].snippet == "2023-11-14 23:13:20 UTC | depth 8 km"
    assert result.results[1].extra["magnitude"] is None
    assert result.results[1].extra["felt_reports"] is None
    assert result.results[1].extra["alert"] is None


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_PAYLOAD),
    )

    result = await _provider().search("5", SearchParams(num_results=1))

    assert len(result.results) == 1
    assert result.results[0].rank == 1


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_PAYLOAD),
    )

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        "not a dict",
        ["a", "list"],
        {"features": "not a list"},
        {"features": [None, "x", 3, {}, {"properties": {}}]},
        {},
    ],
)
async def test_search_handles_unexpected_payload_shapes(respx_mock, payload) -> None:
    respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=payload),
    )

    result = await _provider().search("japan", SearchParams(num_results=5))

    assert result.results == []


def test_build_result_returns_none_without_place_or_url() -> None:
    p = _provider()
    assert p._build_result({"properties": {}}, 1) is None
    assert p._build_result({"properties": "nope"}, 1) is None
    assert p._build_result({}, 1) is None


def test_build_result_handles_missing_geometry() -> None:
    built = _provider()._build_result(
        {
            "properties": {
                "mag": 4.0,
                "place": "Somewhere",
                "time": None,
                "url": "https://earthquake.usgs.gov/e/1",
            },
        },
        1,
    )
    assert built is not None
    assert built.title == "M 4 - Somewhere"
    assert built.published_date is None
    assert built.extra["depth_km"] is None
    assert built.extra["latitude"] is None


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_API_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("japan", SearchParams(num_results=5))
