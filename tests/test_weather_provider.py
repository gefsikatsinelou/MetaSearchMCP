"""Unit tests for the Open-Meteo weather forecast provider."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.weather import WeatherProvider

_GEOCODE_RE = r"https://geocoding-api\.open-meteo\.com/v1/search.*"
_FORECAST_RE = r"https://api\.open-meteo\.com/v1/forecast.*"

_BERLIN_PLACE: dict[str, Any] = {
    "id": 2950159,
    "name": "Berlin",
    "latitude": 52.52437,
    "longitude": 13.41053,
    "elevation": 74.0,
    "feature_code": "PPLC",
    "country_code": "DE",
    "timezone": "Europe/Berlin",
    "population": 3426354,
    "country_id": 2921044,
    "country": "Germany",
    "admin1": "Berlin",
}

_BERLIN_FORECAST: dict[str, Any] = {
    "latitude": 52.52,
    "longitude": 13.419998,
    "timezone": "Europe/Berlin",
    "current": {
        "time": "2026-09-25T05:30",
        "interval": 900,
        "temperature_2m": 12.6,
        "relative_humidity_2m": 85,
        "apparent_temperature": 11.3,
        "precipitation": 0.0,
        "weather_code": 3,
        "wind_speed_10m": 9.4,
    },
    "daily": {
        "time": [
            "2026-09-25",
            "2026-09-26",
            "2026-09-27",
            "2026-09-28",
            "2026-09-29",
        ],
        "weather_code": [3, 61, 0, 2, 95],
        "temperature_2m_max": [15.4, 20.0, 21.2, 18.5, 16.1],
        "temperature_2m_min": [12.3, 8.5, 12.1, 9.9, 7.4],
        "precipitation_probability_max": [30, 96, 0, 20, 75],
    },
}

_EXPECTED_CURRENT = (
    "12.6 °C (feels like 11.3 °C), overcast, humidity 85%, wind 9.4 km/h"
)
_EXPECTED_DAYS = (
    "2026-09-25 15.4/12.3 °C, overcast, 30% rain | "
    "2026-09-26 20/8.5 °C, slight rain, 96% rain | "
    "2026-09-27 21.2/12.1 °C, clear sky, 0% rain"
)
_EXPECTED_SNIPPET = f"{_EXPECTED_CURRENT} | {_EXPECTED_DAYS}"


def _geocode_payload(*places: dict[str, Any]) -> dict[str, Any]:
    """Build an Open-Meteo geocoding response for *places*."""
    return {"results": list(places)}


def _search_params(num_results: int = 10) -> SearchParams:
    """Return search params with a deterministic provider result count."""
    return SearchParams(num_results=num_results)


def test_weather_name_tags_and_availability() -> None:
    p = WeatherProvider()
    assert p.name == "weather"
    assert p.tags == ["weather", "places", "reference"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_weather_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "weather" in registry
    assert registry["weather"].tags == ["weather", "places", "reference"]
    # The geocoding sibling stays untouched and separately registered.
    assert "openmeteo" in registry


def test_weather_place_query_strips_weather_words() -> None:
    from metasearchmcp.providers.weather import _place_query

    assert _place_query("Berlin") == "Berlin"
    assert _place_query("  weather in Tokyo  ") == "Tokyo"
    assert _place_query("forecast for New York tomorrow") == "New York"
    assert _place_query("temperature at Paris now, please") == "Paris"
    assert _place_query("Weather: Berlin today") == "Berlin"
    assert _place_query("São Paulo") == "São Paulo"


def test_weather_place_query_without_place_is_empty() -> None:
    from metasearchmcp.providers.weather import _place_query

    assert _place_query("weather") == ""
    assert _place_query("forecast today") == ""
    assert _place_query("   ") == ""


def test_weather_describe_maps_wmo_codes() -> None:
    from metasearchmcp.providers.weather import _describe

    assert _describe(0) == "clear sky"
    assert _describe(3) == "overcast"
    assert _describe(63) == "moderate rain"
    assert _describe(95) == "thunderstorm"
    # Unknown codes and non-numeric values have no description.
    assert _describe(7) == ""
    assert _describe(None) == ""
    assert _describe("3") == ""
    assert _describe(True) == ""


def test_weather_parse_places_skips_junk_and_preserves_order() -> None:
    from metasearchmcp.providers.weather import _parse_places

    tokyo = {**_BERLIN_PLACE, "name": "Tokyo", "admin1": "Tokyo", "country": "Japan"}
    payload = {
        "results": [
            _BERLIN_PLACE,
            {"name": "Nowhere"},
            {"name": "  ", "latitude": 1.0, "longitude": 2.0},
            {"name": "Bad coords", "latitude": "x", "longitude": 2.0},
            {"name": None, "latitude": 1.0, "longitude": 2.0},
            "junk",
            tokyo,
        ]
    }
    parsed = _parse_places(payload)

    assert [place["name"] for place in parsed] == ["Berlin", "Tokyo"]
    assert parsed[0]["latitude"] == 52.52437
    assert parsed[0]["longitude"] == 13.41053
    assert parsed[0]["country"] == "Germany"
    assert parsed[0]["country_code"] == "DE"
    assert parsed[0]["admin1"] == "Berlin"
    assert parsed[0]["timezone"] == "Europe/Berlin"
    assert parsed[0]["population"] == 3426354
    assert parsed[0]["elevation"] == 74.0


def test_weather_parse_places_malformed_payloads() -> None:
    from metasearchmcp.providers.weather import _parse_places

    assert _parse_places(None) == []
    assert _parse_places([]) == []
    assert _parse_places("nope") == []
    assert _parse_places({}) == []
    assert _parse_places({"results": "nope"}) == []
    assert _parse_places({"results": {}}) == []


def test_weather_current_parses_fields() -> None:
    from metasearchmcp.providers.weather import _current

    current = _current(_BERLIN_FORECAST)
    assert current == {
        "time": "2026-09-25T05:30",
        "temperature": 12.6,
        "apparent_temperature": 11.3,
        "humidity": 85,
        "precipitation": 0.0,
        "wind_speed": 9.4,
        "weather_code": 3,
        "description": "overcast",
    }


def test_weather_current_tolerates_missing_and_odd_fields() -> None:
    from metasearchmcp.providers.weather import _current

    assert _current(None) == {}
    assert _current({}) == {}
    assert _current({"current": "nope"}) == {}

    partial = _current(
        {
            "current": {
                "time": " 2026-09-25T05:30 ",
                "temperature_2m": "12.6",
                "weather_code": 61,
            }
        }
    )
    assert partial["time"] == "2026-09-25T05:30"
    assert partial["temperature"] is None
    assert partial["humidity"] is None
    assert partial["weather_code"] == 61
    assert partial["description"] == "slight rain"


def test_weather_daily_parses_rows() -> None:
    from metasearchmcp.providers.weather import _daily

    rows = _daily(_BERLIN_FORECAST)
    assert [row["date"] for row in rows] == [
        "2026-09-25",
        "2026-09-26",
        "2026-09-27",
        "2026-09-28",
        "2026-09-29",
    ]
    assert rows[0] == {
        "date": "2026-09-25",
        "weather_code": 3,
        "description": "overcast",
        "temperature_max": 15.4,
        "temperature_min": 12.3,
        "precipitation_probability": 30,
    }
    assert rows[1]["description"] == "slight rain"


def test_weather_daily_tolerates_missing_and_odd_fields() -> None:
    from metasearchmcp.providers.weather import _daily

    assert _daily(None) == []
    assert _daily({}) == []
    assert _daily({"daily": "nope"}) == []
    assert _daily({"daily": {"weather_code": [3]}}) == []

    rows = _daily(
        {
            "daily": {
                "time": ["2026-09-25", "", " 2026-09-27T00:00 ", 42],
                "weather_code": [7, "x"],
                "temperature_2m_max": [15.4],
                "temperature_2m_min": [12.3],
                "precipitation_probability_max": [30],
            }
        }
    )
    assert [row["date"] for row in rows] == ["2026-09-25", "2026-09-27"]
    assert rows[0]["temperature_max"] == 15.4
    assert rows[0]["description"] == ""
    assert rows[1]["temperature_max"] is None
    assert rows[1]["precipitation_probability"] is None


def test_weather_place_title_prefers_a_distinct_region() -> None:
    from metasearchmcp.providers.weather import _place_title

    assert _place_title(_BERLIN_PLACE) == "Berlin, Germany"
    assert _place_title({"name": "Springfield", "admin1": "Illinois"}) == (
        "Springfield, Illinois"
    )
    assert _place_title({"name": "Atlantis"}) == "Atlantis"


def test_weather_format_number_drops_trailing_zeros() -> None:
    from metasearchmcp.providers.weather import _format_number

    assert _format_number(12.6, " °C") == "12.6 °C"
    assert _format_number(20.0) == "20"
    assert _format_number(0, "%") == "0%"
    assert _format_number(None, " °C") == ""


def test_weather_snippet_composition() -> None:
    from metasearchmcp.providers.weather import _current, _daily, _snippet

    snippet = _snippet(_current(_BERLIN_FORECAST), _daily(_BERLIN_FORECAST))
    assert snippet == _EXPECTED_SNIPPET
    assert _snippet({}, []) == ""


def test_weather_snippet_truncates_daily_rows() -> None:
    from metasearchmcp.providers.weather import _snippet

    daily = [
        {"date": f"2026-09-{day:02d}", "temperature_max": 20, "temperature_min": 10}
        for day in range(1, 6)
    ]
    snippet = _snippet({}, daily)
    assert "2026-09-01" in snippet
    assert "2026-09-03" in snippet
    assert "2026-09-04" not in snippet


def test_weather_build_result_fields() -> None:
    from metasearchmcp.providers.weather import _current, _daily

    p = WeatherProvider()
    forecast = {
        "timezone": "Europe/Berlin",
        "current": _current(_BERLIN_FORECAST),
        "daily": _daily(_BERLIN_FORECAST),
    }
    r = p._build_result(
        {
            "name": "Berlin",
            "country": "Germany",
            "country_code": "DE",
            "admin1": "Berlin",
            "latitude": 52.52437,
            "longitude": 13.41053,
            "timezone": "Europe/Berlin",
            "population": 3426354,
            "elevation": 74.0,
        },
        forecast,
        total=1,
        rank=1,
    )

    assert r.title == "Berlin, Germany — 12.6 °C, overcast"
    assert r.url == (
        "https://open-meteo.com/en/docs?latitude=52.52437&longitude=13.41053"
    )
    assert r.snippet == _EXPECTED_SNIPPET
    assert r.source == "open-meteo.com"
    assert r.provider == "weather"
    assert r.rank == 1
    assert r.published_date == "2026-09-25T05:30"
    assert r.extra["name"] == "Berlin"
    assert r.extra["region"] == "Berlin"
    assert r.extra["country"] == "Germany"
    assert r.extra["country_code"] == "DE"
    assert r.extra["timezone"] == "Europe/Berlin"
    assert r.extra["population"] == 3426354
    assert r.extra["elevation"] == 74.0
    assert r.extra["forecast_days"] == 5
    assert r.extra["total_results"] == 1
    assert len(r.extra["daily"]) == 5


def test_weather_build_result_without_forecast() -> None:
    p = WeatherProvider()
    r = p._build_result(
        {
            "name": "Atlantis",
            "country": "",
            "country_code": "",
            "admin1": "",
            "latitude": 1.5,
            "longitude": -2.5,
            "timezone": "",
            "population": None,
            "elevation": None,
        },
        {},
        total=1,
        rank=4,
    )

    assert r.title == "Atlantis"
    assert r.url == "https://open-meteo.com/en/docs?latitude=1.5&longitude=-2.5"
    assert r.snippet == ""
    assert r.rank == 4
    assert r.published_date is None
    assert r.extra["current"] == {}
    assert r.extra["daily"] == []


async def test_weather_search_sends_expected_requests(respx_mock) -> None:
    geocode = respx_mock.get(url__regex=_GEOCODE_RE).mock(
        return_value=respx.MockResponse(
            200,
            json=_geocode_payload(_BERLIN_PLACE),
        ),
    )
    forecast = respx_mock.get(url__regex=_FORECAST_RE).mock(
        return_value=respx.MockResponse(200, json=_BERLIN_FORECAST),
    )

    provider = WeatherProvider()
    provider._max_results = 3
    result = await provider.search("  weather in Berlin  ", _search_params(5))

    assert geocode.called
    assert str(geocode.calls[0].request.url) == (
        "https://geocoding-api.open-meteo.com/v1/search"
        "?name=Berlin&count=3&language=en&format=json"
    )
    assert len(forecast.calls) == 1
    assert str(forecast.calls[0].request.url).startswith(
        "https://api.open-meteo.com/v1/forecast?latitude=52.52437&longitude=13.41053",
    )
    assert [r.title for r in result.results] == ["Berlin, Germany — 12.6 °C, overcast"]
    assert result.results[0].extra["total_results"] == 1


async def test_weather_search_caps_places_to_limit(respx_mock) -> None:
    places = [
        {**_BERLIN_PLACE, "name": f"Place {n}", "latitude": 50.0 + n} for n in range(3)
    ]
    geocode = respx_mock.get(url__regex=_GEOCODE_RE).mock(
        return_value=respx.MockResponse(200, json=_geocode_payload(*places)),
    )
    forecast = respx_mock.get(url__regex=_FORECAST_RE).mock(
        return_value=respx.MockResponse(200, json=_BERLIN_FORECAST),
    )

    provider = WeatherProvider()
    provider._max_results = 2
    result = await provider.search("Place", _search_params(50))

    assert "count=2" in str(geocode.calls[0].request.url)
    assert len(result.results) == 2
    assert len(forecast.calls) == 2
    assert result.results[0].extra["total_results"] == 2


async def test_weather_search_tolerates_forecast_failures(respx_mock) -> None:
    respx_mock.get(url__regex=_GEOCODE_RE).mock(
        return_value=respx.MockResponse(
            200,
            json=_geocode_payload(
                _BERLIN_PLACE,
                {**_BERLIN_PLACE, "name": "Potsdam", "latitude": 52.4},
            ),
        ),
    )
    respx_mock.get(url__regex=_FORECAST_RE).mock(
        side_effect=[
            respx.MockResponse(500),
            respx.MockResponse(200, json=_BERLIN_FORECAST),
        ],
    )

    result = await WeatherProvider().search("Berlin", _search_params(2))

    assert [r.title for r in result.results] == [
        "Berlin, Germany",
        "Potsdam, Berlin — 12.6 °C, overcast",
    ]
    assert result.results[0].snippet == ""
    assert result.results[0].extra["timezone"] == "Europe/Berlin"
    assert result.results[1].snippet == _EXPECTED_SNIPPET


async def test_weather_search_skips_forecast_for_unresolved_query(respx_mock) -> None:
    geocode = respx_mock.get(url__regex=_GEOCODE_RE).mock(
        return_value=respx.MockResponse(200, json={"results": []}),
    )
    forecast = respx_mock.get(url__regex=_FORECAST_RE)

    result = await WeatherProvider().search("zzzznotaplace", _search_params())

    assert result.results == []
    assert len(geocode.calls) == 1
    assert not forecast.called


async def test_weather_search_falls_back_to_raw_query(respx_mock) -> None:
    geocode = respx_mock.get(url__regex=_GEOCODE_RE).mock(
        return_value=respx.MockResponse(200, json={"results": []}),
    )

    result = await WeatherProvider().search("weather today", _search_params())

    assert result.results == []
    # Nothing but weather words remains, so the raw query is geocoded.
    assert geocode.calls[0].request.url.params["name"] == "weather today"


async def test_weather_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(url__regex=_GEOCODE_RE)

    result = await WeatherProvider().search("   ", _search_params())

    assert result.results == []
    assert not route.called


async def test_weather_search_zero_limit_skips_request(respx_mock) -> None:
    route = respx_mock.get(url__regex=_GEOCODE_RE)

    provider = WeatherProvider()
    provider._max_results = 0
    result = await provider.search("Berlin", _search_params())

    assert result.results == []
    assert not route.called


async def test_weather_search_raises_on_geocode_http_error(respx_mock) -> None:
    respx_mock.get(url__regex=_GEOCODE_RE).mock(return_value=respx.MockResponse(503))

    with pytest.raises(httpx.HTTPStatusError):
        await WeatherProvider().search("Berlin", _search_params())


async def test_weather_search_handles_malformed_geocode_payload(respx_mock) -> None:
    respx_mock.get(url__regex=_GEOCODE_RE).mock(
        return_value=respx.MockResponse(200, json={"results": "nope"}),
    )

    result = await WeatherProvider().search("Berlin", _search_params())

    assert result.results == []


async def test_weather_search_handles_malformed_forecast_payload(respx_mock) -> None:
    respx_mock.get(url__regex=_GEOCODE_RE).mock(
        return_value=respx.MockResponse(200, json=_geocode_payload(_BERLIN_PLACE)),
    )
    respx_mock.get(url__regex=_FORECAST_RE).mock(
        return_value=respx.MockResponse(200, json=["nope"]),
    )

    result = await WeatherProvider().search("Berlin", _search_params())

    assert [r.title for r in result.results] == ["Berlin, Germany"]
    assert result.results[0].snippet == ""
    assert result.results[0].extra["daily"] == []
