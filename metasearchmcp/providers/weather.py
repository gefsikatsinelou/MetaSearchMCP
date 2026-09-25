"""Weather forecast search via the keyless Open-Meteo APIs.

Open-Meteo (open-meteo.com) publishes free weather APIs backed by national
weather-service models (ICON, GFS, IFS, ...).  They require no API key and
are split over two endpoints:

    GET https://geocoding-api.open-meteo.com/v1/search?name=Berlin
    GET https://api.open-meteo.com/v1/forecast?latitude=..&longitude=..

A free-text query (``Berlin``, ``weather in Tokyo``, ``forecast for New
York``) is first resolved into places with the geocoding endpoint; the
resolved matches are then enriched with a forecast request for the current
conditions and a daily forecast.  Each hit carries the place (name, region,
country, coordinates, timezone, population, elevation), the current
temperature, apparent temperature, humidity, wind speed and precipitation
together with the WMO weather-code description, and the daily maximum and
minimum temperature, precipitation probability and weather code for the
next days — plus a link to Open-Meteo for that location.

The provider is keyless, uses only the shared httpx client, and tags itself
``weather``/``places`` so it complements the existing Open-Meteo
place-search provider with actual forecast data.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import httpx

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# Human-facing Open-Meteo page for the resolved coordinates.
_FORECAST_PAGE_URL = "https://open-meteo.com/en/docs"
_SOURCE = "open-meteo.com"
# Geocoded places that get a (concurrent) forecast request.
_MAX_PLACES = 5
# Days requested from the daily forecast endpoint.
_FORECAST_DAYS = 5
# Daily rows quoted in the snippet before the list is cut short.
_MAX_SNIPPET_DAYS = 3
_CURRENT_FIELDS = (
    "temperature_2m,relative_humidity_2m,apparent_temperature,"
    "precipitation,weather_code,wind_speed_10m"
)
_DAILY_FIELDS = (
    "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
)

# Words that announce a weather lookup rather than name a place, so that a
# query such as ``weather in Tokyo`` still geocodes ``Tokyo``.
_WEATHER_WORDS = frozenset({"weather", "forecast", "forecasts", "temperature", "temp"})
# Joining preposition that may follow those words.
_JOINER_WORDS = frozenset({"in", "for", "at", "of", "near"})
# Time-scope words that trail a lookup without naming a place.
_SCOPE_WORDS = frozenset(
    {
        "now",
        "today",
        "tonight",
        "tomorrow",
        "currently",
        "this",
        "week",
        "weekend",
        "please",
    }
)

# WMO 4677 weather codes used by the Open-Meteo forecast API.
_WMO_DESCRIPTIONS: dict[int, str] = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snowfall",
    73: "moderate snowfall",
    75: "heavy snowfall",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _strip_word(token: str) -> str:
    """Return *token* lowercased and stripped of surrounding punctuation."""
    return token.strip(",?.!;:").lower()


def _place_query(query: str) -> str:
    """Reduce a weather query to the place name the geocoder expects.

    Leading weather keywords (``weather``, ``forecast``, ...), the joining
    preposition that may follow them (``in``, ``for``, ...) and trailing
    time-scope words (``today``, ``tomorrow``, ...) are dropped, so that
    ``weather in Tokyo today`` geocodes ``Tokyo``.  A query consisting only
    of such words is returned unchanged, which keeps a lookup that names no
    place an empty result rather than a surprising one.
    """
    tokens = _clean(query).split()
    while tokens and _strip_word(tokens[0]) in _WEATHER_WORDS:
        tokens.pop(0)
    while tokens and _strip_word(tokens[0]) in _JOINER_WORDS:
        tokens.pop(0)
    while tokens and _strip_word(tokens[-1]) in _SCOPE_WORDS:
        tokens.pop()
    return " ".join(tokens)


def _optional_number(value: object) -> int | float | None:
    """Return *value* as a real number, or ``None`` for anything else."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _code_of(value: object) -> int | None:
    """Return *value* as an integer WMO weather code, or ``None``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _describe(code: object) -> str:
    """Return the human-readable description of a WMO weather code."""
    value = _code_of(code)
    if value is None:
        return ""
    return _WMO_DESCRIPTIONS.get(value, "")


def _format_number(value: int | float | None, unit: str = "") -> str:
    """Format a number without trailing zeros, optionally with a unit."""
    if value is None:
        return ""
    return f"{value:g}{unit}"


def _format_coord(value: float) -> str:
    """Format a latitude/longitude, trimming float representation noise."""
    return f"{round(value, 5)}"


def _value_at(block: dict[str, Any], key: str, index: int) -> object:
    """Return ``block[key][index]``, or ``None`` when it does not exist."""
    values = block.get(key)
    if not isinstance(values, (list, tuple)) or index >= len(values):
        return None
    return values[index]


def _parse_places(data: object) -> list[dict[str, Any]]:
    """Extract the geocoded places of a geocoding response.

    Entries without a name or with unusable coordinates are skipped, while
    the API's own relevance order is preserved.  Any other payload shape
    yields an empty list.
    """
    if not isinstance(data, dict):
        return []
    entries = data.get("results")
    if not isinstance(entries, (list, tuple)):
        return []

    places: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = _clean(entry.get("name"))
        latitude = _optional_number(entry.get("latitude"))
        longitude = _optional_number(entry.get("longitude"))
        if not name or latitude is None or longitude is None:
            continue
        places.append(
            {
                "name": name,
                "country": _clean(entry.get("country")),
                "country_code": _clean(entry.get("country_code")),
                "admin1": _clean(entry.get("admin1")),
                "latitude": latitude,
                "longitude": longitude,
                "timezone": _clean(entry.get("timezone")),
                "population": _optional_number(entry.get("population")),
                "elevation": _optional_number(entry.get("elevation")),
            }
        )
    return places


def _current(data: object) -> dict[str, Any]:
    """Extract the current-conditions block of a forecast response.

    Every value is optional: a missing or non-numeric field is reported as
    ``None`` so a partial forecast still yields a usable result.
    """
    if not isinstance(data, dict):
        return {}
    block = data.get("current")
    if not isinstance(block, dict):
        return {}
    return {
        "time": _clean(block.get("time")),
        "temperature": _optional_number(block.get("temperature_2m")),
        "apparent_temperature": _optional_number(
            block.get("apparent_temperature"),
        ),
        "humidity": _optional_number(block.get("relative_humidity_2m")),
        "precipitation": _optional_number(block.get("precipitation")),
        "wind_speed": _optional_number(block.get("wind_speed_10m")),
        "weather_code": _code_of(block.get("weather_code")),
        "description": _describe(block.get("weather_code")),
    }


def _daily(data: object) -> list[dict[str, Any]]:
    """Extract the daily forecast rows of a forecast response.

    The API returns parallel arrays per day; they are zipped back into one
    row per date, preserving the API's order (today first).
    """
    if not isinstance(data, dict):
        return []
    block = data.get("daily")
    if not isinstance(block, dict):
        return []
    dates = block.get("time")
    if not isinstance(dates, (list, tuple)):
        return []

    rows: list[dict[str, Any]] = []
    for index, raw_date in enumerate(dates):
        date = _clean(raw_date)[:10]
        if not date:
            continue
        code = _value_at(block, "weather_code", index)
        rows.append(
            {
                "date": date,
                "weather_code": _code_of(code),
                "description": _describe(code),
                "temperature_max": _optional_number(
                    _value_at(block, "temperature_2m_max", index),
                ),
                "temperature_min": _optional_number(
                    _value_at(block, "temperature_2m_min", index),
                ),
                "precipitation_probability": _optional_number(
                    _value_at(block, "precipitation_probability_max", index),
                ),
            }
        )
    return rows


def _place_title(place: dict[str, Any]) -> str:
    """Build a readable ``Name, Region`` title for a geocoded place."""
    name = place.get("name") or "Unknown place"
    context = next(
        (
            part
            for part in (place.get("admin1"), place.get("country"))
            if part and part != name
        ),
        "",
    )
    if context:
        return f"{name}, {context}"
    return name


def _current_headline(current: dict[str, Any]) -> str:
    """Build the short current-conditions headline used in the title."""
    parts: list[str] = []
    temperature = current.get("temperature")
    if temperature is not None:
        parts.append(_format_number(temperature, " °C"))
    description = current.get("description")
    if description:
        parts.append(str(description))
    return ", ".join(parts)


def _current_snippet(current: dict[str, Any]) -> str:
    """Compose the current-conditions part of a result snippet."""
    parts: list[str] = []
    temperature = current.get("temperature")
    if temperature is not None:
        text = _format_number(temperature, " °C")
        apparent = current.get("apparent_temperature")
        if apparent is not None:
            text += f" (feels like {_format_number(apparent, ' °C')})"
        parts.append(text)
    if current.get("description"):
        parts.append(str(current["description"]))
    humidity = current.get("humidity")
    if humidity is not None:
        parts.append(f"humidity {_format_number(humidity, '%')}")
    wind = current.get("wind_speed")
    if wind is not None:
        parts.append(f"wind {_format_number(wind, ' km/h')}")
    return ", ".join(parts)


def _daily_snippet(daily: list[dict[str, Any]]) -> str:
    """Compose the daily-forecast part of a result snippet."""
    parts: list[str] = []
    for day in daily[:_MAX_SNIPPET_DAYS]:
        text = day["date"]
        high = day.get("temperature_max")
        low = day.get("temperature_min")
        if high is not None and low is not None:
            text += f" {_format_number(high)}/{_format_number(low)} °C"
        if day.get("description"):
            text += f", {day['description']}"
        rain = day.get("precipitation_probability")
        if rain is not None:
            text += f", {_format_number(rain, '%')} rain"
        parts.append(text)
    return " | ".join(parts)


def _snippet(current: dict[str, Any], daily: list[dict[str, Any]]) -> str:
    """Compose a result snippet from current conditions and daily rows."""
    parts = [
        part for part in (_current_snippet(current), _daily_snippet(daily)) if part
    ]
    return " | ".join(parts)[:MAX_SNIPPET_LENGTH]


class WeatherProvider(BaseProvider):
    """Search current weather and daily forecasts for a place.

    Keyless.  *query* is a place name, optionally wrapped in weather words
    (``Berlin``, ``weather in Tokyo``, ``forecast for New York``).  Each hit
    is one resolved place with its current conditions and the daily forecast
    for the next days, plus a link to Open-Meteo for that location.
    """

    name = "weather"
    description = (
        "Search current weather and daily forecasts for a place — "
        "temperature, apparent temperature, humidity, wind, WMO weather "
        "conditions and the daily high/low with precipitation probability "
        "via the keyless Open-Meteo APIs. No API key required."
    )
    tags: ClassVar[list[str]] = ["weather", "places", "reference"]

    def _build_result(
        self,
        place: dict[str, Any],
        forecast: dict[str, Any],
        total: int,
        rank: int,
    ) -> SearchResult:
        """Build one :class:`SearchResult` from a place and its forecast."""
        current = forecast.get("current") or {}
        daily = forecast.get("daily") or []

        title = _place_title(place)
        headline = _current_headline(current)
        if headline:
            title = f"{title} — {headline}"

        latitude = place["latitude"]
        longitude = place["longitude"]
        return SearchResult(
            title=title,
            url=(
                f"{_FORECAST_PAGE_URL}?latitude={_format_coord(latitude)}"
                f"&longitude={_format_coord(longitude)}"
            ),
            snippet=_snippet(current, daily),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            published_date=current.get("time") or None,
            extra={
                "name": place["name"],
                "region": place["admin1"],
                "country": place["country"],
                "country_code": place["country_code"],
                "latitude": latitude,
                "longitude": longitude,
                "timezone": forecast.get("timezone") or place["timezone"],
                "population": place["population"],
                "elevation": place["elevation"],
                "current": current,
                "daily": daily,
                "forecast_days": _FORECAST_DAYS,
                "total_results": total,
            },
        )

    async def _geocode(
        self,
        client: httpx.AsyncClient,
        place: str,
        count: int,
        language: str,
    ) -> list[dict[str, Any]]:
        """Resolve *place* into geocoded locations."""
        resp = await client.get(
            _GEOCODE_URL,
            params={
                "name": place,
                "count": str(count),
                "language": language or "en",
                "format": "json",
            },
        )
        resp.raise_for_status()
        return _parse_places(resp.json())

    async def _forecast(
        self,
        client: httpx.AsyncClient,
        place: dict[str, Any],
    ) -> dict[str, Any]:
        """Fetch the current conditions and daily forecast of *place*."""
        resp = await client.get(
            _FORECAST_URL,
            params={
                "latitude": _format_coord(place["latitude"]),
                "longitude": _format_coord(place["longitude"]),
                "current": _CURRENT_FIELDS,
                "daily": _DAILY_FIELDS,
                "forecast_days": str(_FORECAST_DAYS),
                "timezone": "auto",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            data = {}
        return {
            "timezone": _clean(data.get("timezone")),
            "current": _current(data),
            "daily": _daily(data),
        }

    async def _forecasts(
        self,
        client: httpx.AsyncClient,
        places: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Fetch the forecasts of *places*, tolerating failures.

        All forecast requests run concurrently and the outcomes stay
        positionally aligned with *places*; a place whose lookup fails is
        returned without forecast data instead of failing the whole search.
        """
        if not places:
            return []
        outcomes = await asyncio.gather(
            *(self._forecast(client, place) for place in places),
            return_exceptions=True,
        )
        return [outcome if isinstance(outcome, dict) else {} for outcome in outcomes]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the weather of the places matching *query*.

        A blank query performs no request.  The query is reduced to a place
        name before geocoding; the returned matches are then enriched with a
        forecast in a second round of concurrent, failure-tolerant requests,
        so only the geocoding request itself can fail the search.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_PLACES)
        if limit <= 0:
            return ProviderResult(results=[])

        async with self._client() as client:
            places = await self._geocode(
                client,
                _place_query(cleaned) or cleaned,
                limit,
                params.language,
            )
            # Defensive: never trust the API to honour the requested count.
            places = places[:limit]
            forecasts = await self._forecasts(client, places)

        results = [
            self._build_result(place, forecast, len(places), rank)
            for rank, (place, forecast) in enumerate(
                zip(places, forecasts, strict=True),
                start=1,
            )
        ]
        return ProviderResult(results=results)
