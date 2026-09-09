"""Space launch database search via the keyless Launch Library 2 API.

Launch Library 2 (``ll.thespacedevs.com``) is The Space Devs' free,
community-curated database of orbital and suborbital space launches,
covering historical flights (Apollo, Shuttle, ...) as well as upcoming
missions.  Its read-only JSON API requires no API key:

``GET https://ll.thespacedevs.com/2.2.0/launch/?search=QUERY&limit=N``

Each hit is a launch event carrying the launch name (``Rocket | Mission``),
status (Success / Go for Launch / TBD ...), launch date (``net``), rocket
configuration, mission name/type/description and orbit, and the launch pad
with its location.

This complements the existing NASA (imagery) and Spaceflight News (articles)
providers by exposing the underlying launch/rocket/mission database, which
none of the current providers offer.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://ll.thespacedevs.com/2.2.0/launch/"
# Landing page for a launch event on the Space Launch Now front end.
_DETAILS_URL = "https://spacelaunchnow.me/launch"
# The API caps a page at 100 items; keep requests modest out of courtesy.
_MAX_API_RESULTS = 25


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _image_url(value: object) -> str:
    """Extract the image URL, tolerating both dict and plain-string forms."""
    if isinstance(value, dict):
        return _clean(value.get("image_url"))
    return _clean(value)


class SpaceLaunchProvider(BaseProvider):
    """Search the Launch Library 2 space launch database.

    Keyless.  Matches launch events by name, rocket, mission and pad, e.g.
    ``\"falcon heavy\"`` or ``\"apollo 11\"``; each hit carries the launch
    date, status, rocket configuration, mission details and pad location.
    """

    name = "spacelaunch"
    description = (
        "Search space launches, rockets and missions in the Launch Library 2 "
        "database (historical and upcoming launches with dates, status and "
        "pad info), no API key required."
    )
    tags: ClassVar[list[str]] = ["space", "science"]

    @staticmethod
    def _labeled(pairs: list[tuple[str, str]]) -> list[str]:
        """Build ``\"Label: value\"`` parts, skipping empty values."""
        return [f"{label}: {value}" for label, value in pairs if value]

    def _parse(self, data: Any, limit: int | None = None) -> ProviderResult:
        """Parse a Launch Library 2 search response into results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in data.get("results") or []:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue

            title = _clean(item.get("name"))
            slug = _clean(item.get("slug"))
            if not title:
                continue

            mission = item.get("mission")
            mission_name = ""
            description = ""
            orbit = ""
            if isinstance(mission, dict):
                mission_name = _clean(mission.get("name"))
                description = _clean(mission.get("description"))
                orbit_info = mission.get("orbit")
                if isinstance(orbit_info, dict):
                    orbit = _clean(orbit_info.get("name"))

            status = item.get("status")
            status_dict = status if isinstance(status, dict) else {}
            status_abbrev = _clean(status_dict.get("abbrev"))
            rocket = item.get("rocket")
            rocket_name = ""
            if isinstance(rocket, dict):
                configuration = rocket.get("configuration")
                if isinstance(configuration, dict):
                    rocket_name = _clean(configuration.get("full_name"))

            pad = item.get("pad")
            pad_name = ""
            location = ""
            if isinstance(pad, dict):
                pad_name = _clean(pad.get("name"))
                pad_location = pad.get("location")
                if isinstance(pad_location, dict):
                    location = _clean(pad_location.get("name"))

            provider = item.get("launch_service_provider")
            agency = _clean(provider.get("name")) if isinstance(provider, dict) else ""

            parts = [
                description,
                *self._labeled(
                    [
                        ("Date", self._iso_date_prefix(item.get("net"))),
                        ("Rocket", rocket_name),
                        ("Status", status_abbrev),
                        ("Orbit", orbit),
                        ("Pad", f"{pad_name} ({location})" if location else pad_name),
                        ("Agency", agency),
                    ]
                ),
            ]
            snippet = " | ".join(part for part in parts if part)[:MAX_SNIPPET_LENGTH]

            if slug:
                url = f"{_DETAILS_URL}/{quote(slug, safe='')}/"
            else:
                url = _clean(item.get("url"))

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source="spacelaunchnow.me",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "type": "launch",
                        "launch_id": _clean(item.get("id")),
                        "slug": slug,
                        "net": _clean(item.get("net")),
                        "status": status_abbrev,
                        "rocket": rocket_name,
                        "mission_name": mission_name,
                        "orbit": orbit,
                        "pad": pad_name,
                        "location": location,
                        "launch_service_provider": agency,
                        "image_url": _image_url(item.get("image")),
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Launch Library 2 for launches matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        request_params = {"search": query, "limit": limit}
        async with self._client() as client:
            resp = await client.get(_API_URL, params=request_params)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
