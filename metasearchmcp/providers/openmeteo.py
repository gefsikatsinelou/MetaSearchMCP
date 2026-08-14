"""Open-Meteo Geocoding place search via the public REST API.

Open-Meteo's geocoding service resolves place names into structured
geographic data (coordinates, country, administrative divisions, population,
and timezone) without requiring an API key.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://geocoding-api.open-meteo.com/v1/search"
_MAX_API_RESULTS = 20


class OpenMeteoProvider(BaseProvider):
    """Open-Meteo Geocoding place search.

    No authentication required; free for non-commercial and low-volume use.
    """

    name = "openmeteo"
    description = (
        "Search and geocode places worldwide — cities, regions, and landmarks "
        "with coordinates, population, and timezone via Open-Meteo."
    )
    tags: ClassVar[list[str]] = ["places", "geography", "maps"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Geocode *query* into structured place results."""
        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={
                    "name": query,
                    "count": str(
                        min(params.num_results, self._max_results, _MAX_API_RESULTS),
                    ),
                    "language": params.language or "en",
                    "format": "json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    @staticmethod
    def _place_title(item: dict[str, Any]) -> str:
        """Build a readable title for a place result."""
        name = item.get("name") or "Unknown place"
        context = item.get("admin1") or item.get("country") or ""
        if context and context != name:
            return f"{name}, {context}"
        return name

    @staticmethod
    def _place_url(item: dict[str, Any]) -> str:
        """Build an OpenStreetMap link for a place's coordinates."""
        lat = item.get("latitude")
        lon = item.get("longitude")
        if lat is None or lon is None:
            return ""
        return (
            f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=12/{lat}/{lon}"
        )

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the geocoding API response into structured search results."""
        results: list[SearchResult] = []

        for i, item in enumerate(data.get("results") or [], start=1):
            country = item.get("country") or ""
            admin1 = item.get("admin1") or ""
            timezone = item.get("timezone") or ""
            population = item.get("population")
            elevation = item.get("elevation")

            snippet_parts: list[str] = []
            if country:
                snippet_parts.append(f"Country: {country}")
            if admin1:
                snippet_parts.append(f"Region: {admin1}")
            if population:
                snippet_parts.append(f"Population: {population:,}")
            if timezone:
                snippet_parts.append(f"Timezone: {timezone}")
            if elevation is not None:
                snippet_parts.append(f"Elevation: {elevation:g} m")

            results.append(
                SearchResult(
                    title=self._place_title(item),
                    url=self._place_url(item),
                    snippet=" | ".join(snippet_parts),
                    source="openstreetmap.org",
                    rank=i,
                    provider=self.name,
                    extra={
                        "place_id": item.get("id"),
                        "latitude": item.get("latitude"),
                        "longitude": item.get("longitude"),
                        "elevation": elevation,
                        "country_code": item.get("country_code"),
                        "country": country,
                        "admin1": admin1,
                        "admin2": item.get("admin2") or "",
                        "population": population,
                        "timezone": timezone,
                        "postcodes": item.get("postcodes") or [],
                    },
                ),
            )

        return ProviderResult(results=results)
