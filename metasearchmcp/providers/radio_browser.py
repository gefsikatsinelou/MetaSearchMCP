"""Radio Browser radio station search via the keyless public API.

Radio Browser (radio-browser.info) is a community-maintained directory of
internet radio stations. Its public JSON API requires no API key:

``GET https://all.api.radio-browser.info/json/stations/search?name=QUERY``

The ``all.`` host redirects to a random healthy mirror, so requests are
resilient to individual mirror outages. Each hit carries the station name,
homepage, live stream URL, country, language, tags, codec, bitrate, and
community vote count. No authentication is required; parsing uses the shared
httpx client from the base provider.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://all.api.radio-browser.info/json/stations/search"
# Radio Browser asks clients to stay under ~1 request/second; one per search is fine.
_MAX_API_RESULTS = 30


class RadioBrowserProvider(BaseProvider):
    """Search internet radio stations via Radio Browser.

    Uses the keyless public API, which requires no authentication and returns
    structured station metadata: name, homepage, live stream URL, country,
    language, tags, codec, bitrate, and community vote count.
    """

    name = "radio_browser"
    description = (
        "Search internet radio stations by name or genre — country, language, "
        "stream URL, and codec info via the keyless Radio Browser API."
    )
    tags: ClassVar[list[str]] = ["media", "audio", "radio"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _stream_info(codec: str, bitrate: object) -> str:
        """Compose a short stream descriptor like ``MP3 128 kbps``."""
        parts = [part for part in (codec, f"{bitrate} kbps" if bitrate else "") if part]
        return " ".join(parts)

    def _parse(self, data: Any) -> ProviderResult:
        """Parse the Radio Browser response into structured search results."""
        results: list[SearchResult] = []
        if not isinstance(data, list):
            return ProviderResult(results=results)

        for i, station in enumerate(data, start=1):
            if not isinstance(station, dict):
                continue

            name = self._clean_text(station.get("name"))
            homepage = str(station.get("homepage") or "").strip()
            stream_url = str(
                station.get("url_resolved") or station.get("url") or ""
            ).strip()
            if not name or not (homepage or stream_url):
                continue

            country = self._clean_text(station.get("country"))
            language = self._clean_text(station.get("language"))
            codec = self._clean_text(station.get("codec"))
            bitrate = station.get("bitrate")
            tags = [
                t.strip()
                for t in str(station.get("tags") or "").split(",")
                if t.strip()
            ]

            snippet_parts: list[str] = []
            if tags:
                snippet_parts.append(f"Tags: {', '.join(tags[:8])}")
            if country:
                snippet_parts.append(f"Country: {country}")
            if language:
                snippet_parts.append(f"Language: {language}")
            stream_info = self._stream_info(codec, bitrate)
            if stream_info:
                snippet_parts.append(f"Stream: {stream_info}")

            results.append(
                SearchResult(
                    title=name,
                    url=homepage or stream_url,
                    snippet=" | ".join(snippet_parts),
                    source="radio-browser.info",
                    rank=i,
                    provider=self.name,
                    extra={
                        "stream_url": stream_url,
                        "homepage": homepage,
                        "favicon": str(station.get("favicon") or ""),
                        "country": country,
                        "country_code": str(station.get("countrycode") or ""),
                        "state": self._clean_text(station.get("state")),
                        "language": language,
                        "tags": tags,
                        "codec": codec,
                        "bitrate": bitrate,
                        "votes": station.get("votes"),
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Radio Browser for stations matching *query*.

        Stations are ordered by community vote count (most voted first) and
        broken streams are hidden.
        """
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {
            "name": query,
            "limit": limit,
            "hidebroken": "true",
            "order": "votes",
            "reverse": "true",
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        result = self._parse(data)
        # Truncate to the requested limit (the API may still return more).
        result.results = result.results[:limit]
        return result
