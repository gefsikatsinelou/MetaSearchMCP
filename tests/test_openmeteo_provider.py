"""Unit tests for the Open-Meteo Geocoding place search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.openmeteo import OpenMeteoProvider

_SAMPLE_RESPONSE = {
    "results": [
        {
            "id": 2950159,
            "name": "Berlin",
            "latitude": 52.52437,
            "longitude": 13.41053,
            "elevation": 39.0,
            "feature_code": "PPLC",
            "country_code": "DE",
            "admin1": "State of Berlin",
            "admin2": "Berlin",
            "country": "Germany",
            "population": 3426354,
            "postcodes": ["10115", "10117"],
            "timezone": "Europe/Berlin",
        },
        {
            "id": 2657896,
            "name": "Berlin",
            "latitude": 44.46867,
            "longitude": -71.18508,
            "elevation": 312.0,
            "feature_code": "PPL",
            "country_code": "US",
            "admin1": "New Hampshire",
            "admin2": "Coos",
            "country": "United States",
            "population": 9367,
            "postcodes": [],
            "timezone": "America/New_York",
        },
    ],
    "generationtime_ms": 0.38,
}

_EMPTY_RESPONSE = {"generationtime_ms": 0.2}


def test_openmeteo_parse_basic():
    p = OpenMeteoProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Berlin, State of Berlin"
    assert "openstreetmap.org" in r.url
    assert "Country: Germany" in r.snippet
    assert "Population: 3,426,354" in r.snippet
    assert "Timezone: Europe/Berlin" in r.snippet
    assert r.source == "openstreetmap.org"
    assert r.provider == "openmeteo"
    assert r.rank == 1
    assert r.extra["latitude"] == 52.52437
    assert r.extra["longitude"] == 13.41053
    assert r.extra["country_code"] == "DE"
    assert r.extra["population"] == 3426354
    assert r.extra["timezone"] == "Europe/Berlin"
    assert r.extra["postcodes"] == ["10115", "10117"]


def test_openmeteo_parse_ranks():
    p = OpenMeteoProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    assert result.results[0].rank == 1
    assert result.results[1].rank == 2


def test_openmeteo_parse_empty():
    p = OpenMeteoProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_openmeteo_parse_missing_keys():
    p = OpenMeteoProvider()
    result = p._parse({"results": [{"name": "Nowhere"}]})
    r = result.results[0]
    assert r.title == "Nowhere"
    assert r.url == ""
    assert r.snippet == ""
    assert r.extra["latitude"] is None
    assert r.extra["country_code"] is None
    assert r.extra["population"] is None


def test_openmeteo_parse_no_results_key():
    p = OpenMeteoProvider()
    result = p._parse({})
    assert result.results == []


def test_openmeteo_place_title():
    assert OpenMeteoProvider._place_title({"name": "Paris", "country": "France"}) == (
        "Paris, France"
    )
    assert OpenMeteoProvider._place_title({"name": "Paris"}) == "Paris"
    assert OpenMeteoProvider._place_title({}) == "Unknown place"


def test_openmeteo_place_url():
    url = OpenMeteoProvider._place_url({"latitude": 52.5, "longitude": 13.4})
    assert "mlat=52.5" in url
    assert "mlon=13.4" in url
    assert OpenMeteoProvider._place_url({}) == ""
    assert OpenMeteoProvider._place_url({"latitude": 1.0}) == ""


def test_openmeteo_is_available():
    """Keyless provider is always available."""
    assert OpenMeteoProvider().is_available() is True


@pytest.mark.asyncio
async def test_openmeteo_search_builds_query(respx_mock):
    """The search method hits the geocoding endpoint and parses the response."""
    import respx

    respx_mock.get("https://geocoding-api.open-meteo.com/v1/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = OpenMeteoProvider()
    result = await p.search("berlin", SearchParams(num_results=5, language="en"))

    assert len(result.results) == 2
    assert result.results[0].provider == "openmeteo"
    assert result.results[0].title == "Berlin, State of Berlin"


@pytest.mark.asyncio
async def test_openmeteo_search_passes_language(respx_mock):
    """The search method forwards the language parameter to the API."""
    import respx

    route = respx_mock.get("https://geocoding-api.open-meteo.com/v1/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = OpenMeteoProvider()
    await p.search("berlin", SearchParams(num_results=3, language="de"))

    request = route.calls.last.request
    assert request.url.params["language"] == "de"
    assert request.url.params["name"] == "berlin"
    assert request.url.params["count"] == "3"
