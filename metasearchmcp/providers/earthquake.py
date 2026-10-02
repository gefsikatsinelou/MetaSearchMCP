"""Recent-earthquake search via the keyless USGS Earthquake Catalog API.

``USGS`` (https://earthquake.usgs.gov) publishes the world's authoritative
seismic event catalogue through its ``fdsnws/event/1/query`` endpoint.  The
service is keyless and returns GeoJSON::

    GET https://earthquake.usgs.gov/fdsnws/event/1/query
        ?format=geojson&orderby=time&limit=500[&starttime=YYYY-MM-DD|&minmagnitude=X]

Each feature carries ``properties`` (``place``, ``mag``, ``time`` as epoch
milliseconds, ``url``, ``tsunami``, ``felt``, ``alert``, ``sig``) and a
``geometry`` whose ``coordinates`` are ``[longitude, latitude, depth_km]``.

The FDSN API has no free-text parameter, so a place-name query (e.g.
``"japan"``) is honoured by fetching a bounded window of recent events and
matching it against each event's ``place`` string client-side.  A purely
numeric query is instead interpreted as a minimum magnitude, matching the
catalogue's own ``minmagnitude`` filter.  No API key is required.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
# The catalogue allows up to 20,000 events per call, but a bounded window keeps
# responses small while still giving place-name filters enough to match against.
_MAX_FETCH = 500
# Cap results regardless of what the client asks for.
_MAX_RESULTS = 50
# Default lookback window for place-name queries.
_LOOKBACK_DAYS = 30


def _as_magnitude(query: str) -> float | None:
    """Return *query* as a float magnitude, or ``None`` when it is not numeric."""
    try:
        return float(query)
    except ValueError:
        return None


def _iso_datetime_from_ms(value: Any) -> str | None:
    """Convert an epoch-milliseconds timestamp to an ISO-8601 UTC string."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        moment = datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return moment.isoformat()


def _number(value: Any) -> float | None:
    """Return *value* as a float, or ``None`` when it is not a real number."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return value


class EarthquakeProvider(BaseProvider):
    """Search recent earthquakes in the keyless USGS Earthquake Catalog.

    A place-name query matches against each event's location description
    (e.g. ``"10 km SSW of Japan"``); a numeric query selects every event at
    or above that magnitude in the recent window.  Results are ordered by most
    recent, and each hit exposes magnitude, depth, coordinates, tsunami and
    alert metadata so agents get structured seismic facts rather than prose.
    """

    name = "earthquake"
    description = (
        "Search recent earthquakes from the USGS Earthquake Catalog by place "
        "name, or by minimum magnitude for a numeric query, returning "
        "magnitude, depth, coordinates and tsunami/alert metadata, "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["science", "geo", "news"]

    def _build_result(self, feature: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw GeoJSON feature."""
        props = feature.get("properties")
        if not isinstance(props, dict):
            return None

        place = props.get("place")
        place = place.strip() if isinstance(place, str) else ""
        url = props.get("url")
        url = url if isinstance(url, str) else ""
        if not place and not url:
            return None

        magnitude = _number(props.get("mag"))
        if magnitude is not None and place:
            title = f"M {magnitude:g} - {place}"
        else:
            title = place or "Earthquake"

        longitude = latitude = depth = None
        geometry = feature.get("geometry")
        if isinstance(geometry, dict):
            coords = geometry.get("coordinates")
            if isinstance(coords, list) and len(coords) >= 2:
                longitude = _number(coords[0])
                latitude = _number(coords[1])
                if len(coords) >= 3:
                    depth = _number(coords[2])

        iso_datetime = _iso_datetime_from_ms(props.get("time"))
        published_date = iso_datetime[:10] if iso_datetime else None

        tsunami = props.get("tsunami")
        if tsunami not in (0, 1):
            tsunami = None
        felt = props.get("felt")
        if not isinstance(felt, int) or isinstance(felt, bool) or felt <= 0:
            felt = None
        alert = props.get("alert")
        alert = alert if isinstance(alert, str) and alert else None
        significance = props.get("sig")
        if not isinstance(significance, int) or isinstance(significance, bool):
            significance = None

        snippet_parts: list[str] = []
        if iso_datetime:
            snippet_parts.append(
                iso_datetime.replace("T", " ").replace("+00:00", " UTC"),
            )
        if depth is not None:
            snippet_parts.append(f"depth {depth:g} km")
        if tsunami == 1:
            snippet_parts.append("tsunami advisory")
        if felt is not None:
            snippet_parts.append(f"{felt} felt reports")
        if alert is not None:
            snippet_parts.append(f"{alert} alert level")

        return SearchResult(
            title=title,
            url=url,
            snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
            source="earthquake.usgs.gov",
            rank=rank,
            provider=self.name,
            published_date=published_date,
            extra={
                "magnitude": magnitude,
                "place": place or None,
                "depth_km": depth,
                "latitude": latitude,
                "longitude": longitude,
                "tsunami": tsunami,
                "felt_reports": felt,
                "alert": alert,
                "significance": significance,
            },
        )

    def _parse(
        self,
        payload: object,
        query: str,
        min_magnitude: float | None,
        limit: int,
    ) -> list[SearchResult]:
        """Parse a GeoJSON response into ranked results.

        When *min_magnitude* is ``None`` the events are filtered by a
        case-insensitive substring match of *query* against each event's
        ``place``; otherwise every returned event is kept (the catalogue has
        already applied the magnitude filter).  At most *limit* hits are kept.
        """
        results: list[SearchResult] = []
        if not isinstance(payload, dict):
            return results
        features = payload.get("features")
        if not isinstance(features, list):
            return results

        needle = query.lower()
        for feature in features:
            if len(results) >= limit:
                break
            if not isinstance(feature, dict):
                continue
            if min_magnitude is None:
                props = feature.get("properties")
                place = props.get("place") if isinstance(props, dict) else None
                if not isinstance(place, str) or needle not in place.lower():
                    continue
            built = self._build_result(feature, len(results) + 1)
            if built is not None:
                results.append(built)

        return results

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the USGS catalogue for events matching *query*.

        A blank query performs no request.  Results are ordered most-recent
        first (``orderby=time``).
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_RESULTS)
        min_magnitude = _as_magnitude(cleaned)

        api_params: dict[str, str] = {
            "format": "geojson",
            "orderby": "time",
            "limit": str(_MAX_FETCH),
        }
        if min_magnitude is not None:
            api_params["minmagnitude"] = f"{min_magnitude:g}"
        else:
            start = datetime.now(UTC) - timedelta(days=_LOOKBACK_DAYS)
            api_params["starttime"] = start.strftime("%Y-%m-%d")

        async with self._client() as client:
            resp = await client.get(_API_URL, params=api_params)
            resp.raise_for_status()
            payload = resp.json()

        return ProviderResult(
            results=self._parse(payload, cleaned, min_magnitude, limit),
        )
