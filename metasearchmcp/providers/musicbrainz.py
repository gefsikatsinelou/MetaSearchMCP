"""MusicBrainz recording search via the keyless public JSON API.

MusicBrainz is an open music encyclopedia covering recordings, artists,
releases, and works. Its read-only search API requires no API key and
returns clean JSON:

``GET https://musicbrainz.org/ws/2/recording?query=QUERY&fmt=json&limit=N``

The Lucene-style query matches recording titles, artist names, and release
titles. MusicBrainz asks clients to identify themselves with a descriptive
User-Agent; the shared base client already carries one.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://musicbrainz.org/ws/2/recording"


def _format_length(length_ms: int | None) -> str | None:
    """Format a duration in milliseconds as ``M:SS`` (or ``H:MM:SS``)."""
    if not length_ms:
        return None
    total_seconds = length_ms // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


class MusicBrainzProvider(BaseProvider):
    """Search recordings in the MusicBrainz music encyclopedia.

    Uses the keyless read-only JSON API. Query terms match recording
    titles, artist names, and release titles.
    """

    name = "musicbrainz"
    description = (
        "Music recording metadata from the MusicBrainz open encyclopedia "
        "(recordings, artists, releases), no API key required."
    )
    tags: ClassVar[list[str]] = ["music", "media", "knowledge"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search MusicBrainz recordings for *query* and return results."""
        limit = min(params.num_results, self._max_results)
        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={"query": query, "fmt": "json", "limit": str(limit)},
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the API response into structured search results."""
        results: list[SearchResult] = []
        for i, item in enumerate(data.get("recordings", []), start=1):
            if not isinstance(item, dict):
                continue
            recording_id = item.get("id")
            title = item.get("title", "")
            if not recording_id or not title:
                continue

            artist_names = [
                credit.get("name")
                for credit in item.get("artist-credit", [])
                if isinstance(credit, dict)
            ]
            artists = ", ".join(name for name in artist_names if name)
            release_date = item.get("first-release-date") or ""
            length = _format_length(item.get("length"))

            snippet_parts = []
            if artists:
                snippet_parts.append(f"by {artists}")
            if release_date:
                snippet_parts.append(f"first released {release_date}")
            if length:
                snippet_parts.append(length)
            snippet = " · ".join(snippet_parts)

            extra: dict[str, Any] = {}
            score = item.get("score")
            if isinstance(score, (int, float)):
                extra["score"] = round(float(score), 1)
            if artists:
                extra["artists"] = artists
            if release_date:
                extra["first_release_date"] = release_date
            if length:
                extra["length"] = length
            disambiguation = item.get("disambiguation")
            if disambiguation:
                extra["disambiguation"] = disambiguation

            results.append(
                SearchResult(
                    title=title,
                    url=f"https://musicbrainz.org/recording/{recording_id}",
                    snippet=snippet,
                    source="musicbrainz.org",
                    rank=i,
                    provider=self.name,
                    extra=extra,
                ),
            )

        return ProviderResult(results=results)
