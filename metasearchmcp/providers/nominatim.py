"""OpenStreetMap Nominatim geocoding / places search via the public API.

Nominatim indexes addresses, points of interest, and named places from the
OpenStreetMap database. Its public search endpoint requires no API key, but
the service asks clients to identify themselves with a ``User-Agent`` (or
``Referer``) and to limit request rates.

``GET https://nominatim.openstreetmap.org/search?q=QUERY&format=jsonv2``

(Unstructured) search here maps to the broader ``q`` free-text API; each hit
carries the display name, a map ``osm_url`` derived from the type/id, the
place category/type, and, when available, a latitude/longitude and bounding
box. Query parameters use the ``addressdetails``/``limit`` flags to enrich
results without extra round-trips.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim lets us request bounding boxes and structured address details.
_SUPPORTED_FORMAT = "jsonv2"
# The public endpoint allows at most this many results per request.
_MAX_API_RESULTS = 20


class NominatimProvider(BaseProvider):
    """Search OpenStreetMap places and addresses via Nominatim.

    Keyless: uses the public Nominatim search API. Each result carries the
    place's display name, map-page URL, category/type, and — when the source
    provides them — latitude/longitude and a bounding box. A broad ``q``
    query is used so both named landmarks and free-form addresses resolve.
    """

    name = "nominatim"
    description = (
        "Search OpenStreetMap places, addresses, and landmarks via the "
        "keyless Nominatim geocoding API — name, category, coordinates, "
        "and a map link for each result."
    )
    tags: ClassVar[list[str]] = ["places", "geo", "web"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _bbox_string(bbox: object) -> str:
        """Render a bounding box list as ``south,west,north,east``."""
        if not isinstance(bbox, list) or len(bbox) != 4:
            return ""
        return ", ".join(str(v) for v in bbox)

    def _parse(self, data: Any, limit: int | None = None) -> ProviderResult:
        """Parse the Nominatim search response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, list):
            return ProviderResult(results=results)

        items = data[:limit] if limit is not None else data
        for i, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue

            display_name = self._clean_text(item.get("display_name"))
            osm_type = self._clean_text(item.get("osm_type"))
            osm_id = item.get("osm_id")
            if not display_name or not osm_id:
                continue

            # Reference URL on the OpenStreetMap website (note/way/node pages).
            osm_url = (
                f"https://www.openstreetmap.org/{osm_type}/{osm_id}" if osm_type else ""
            )

            category = self._clean_text(item.get("category"))
            place_type = self._clean_text(item.get("type"))
            lat = item.get("lat")
            lon = item.get("lon")
            bbox = self._bbox_string(item.get("boundingbox"))

            snippet_parts: list[str] = []
            if category:
                snippet_parts.append(f"Category: {category}")
            if place_type:
                snippet_parts.append(f"Type: {place_type}")
            if lat and lon:
                snippet_parts.append(f"Coordinates: {lat}, {lon}")
            if bbox:
                snippet_parts.append(f"BBox: {bbox}")

            results.append(
                SearchResult(
                    title=display_name,
                    url=osm_url or "https://www.openstreetmap.org/",
                    snippet=" | ".join(snippet_parts),
                    source="openstreetmap.org",
                    rank=i,
                    provider=self.name,
                    extra={
                        "osm_type": osm_type,
                        "osm_id": str(osm_id),
                        "category": category,
                        "type": place_type,
                        "lat": lat,
                        "lon": lon,
                        "boundingbox": bbox,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Nominatim for OpenStreetMap places matching *query*.

        Sends a free-text ``q`` query plus ``addressdetails``/``limit`` flags
        to enrich results. The response is truncated to the requested count.
        """
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={
                    "q": query,
                    "format": _SUPPORTED_FORMAT,
                    "addressdetails": "0",
                    "limit": str(_MAX_API_RESULTS),
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
