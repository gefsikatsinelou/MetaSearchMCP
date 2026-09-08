"""Deezer music search via the official keyless public API.

Deezer operates one of the largest licensed music-streaming catalogs;
its read-only search endpoint requires no API key or OAuth token:

``GET https://api.deezer.com/search?q=QUERY&limit=N``

The endpoint returns tracks from the Deezer catalog ordered by relevance
and popularity.  Each hit carries the track title, artist and album
names, duration, Deezer rank, explicit-lyrics flag, the canonical
Deezer page URL, and a 30-second MP3 preview URL when available.

Deezer complements the existing MusicBrainz (open metadata encyclopedia)
and Discogs (physical releases) providers by exposing the playable
streaming catalog, with preview URLs that agents can hand to a client.

The public JSON API is rate-limited (about 50 requests / 5 seconds),
which is fine for interactive metasearch traffic.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_SEARCH_URL = "https://api.deezer.com/search"
_MAX_API_RESULTS = 50


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _string(value: object) -> str:
    """Return a cleaned string, or ``""`` for non-string values."""
    return _clean(value) if isinstance(value, str) else ""


def _format_duration(total_seconds: int | None) -> str:
    """Format a duration in seconds as ``M:SS`` (or ``H:MM:SS``)."""
    if not total_seconds or total_seconds <= 0:
        return ""
    hours, remainder = divmod(int(total_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


class DeezerProvider(BaseProvider):
    """Search music tracks in the Deezer streaming catalog.

    Keyless. Uses the official Deezer public search API, which covers the
    whole licensed streaming catalog.  Hits are ordered by Deezer's
    relevance/popularity ranking; each hit carries the artist, album,
    duration, rank and a 30-second preview URL when one exists.
    """

    name = "deezer"
    description = (
        "Search music tracks in the Deezer streaming catalog "
        "(artist/album/duration/preview), no API key required."
    )
    tags: ClassVar[list[str]] = ["music", "media", "web"]

    @staticmethod
    def _artist_name(artist: object) -> str:
        """Return the artist display name from the API artist object."""
        if isinstance(artist, dict):
            return _string(artist.get("name"))
        return ""

    @staticmethod
    def _album_title(album: object) -> str:
        """Return the album title from the API album object."""
        if isinstance(album, dict):
            return _string(album.get("title"))
        return ""

    def _parse(self, data: Any, limit: int | None = None) -> ProviderResult:
        """Parse a Deezer search response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        hits = data.get("data")
        if not isinstance(hits, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in hits[:max_results]:
            if not isinstance(item, dict):
                continue
            title = _string(item.get("title"))
            url = _string(item.get("link"))
            if not title or not url:
                continue

            artist = self._artist_name(item.get("artist"))
            album = self._album_title(item.get("album"))
            duration_seconds = item.get("duration")
            if not isinstance(duration_seconds, int):
                duration_seconds = 0
            explicit = bool(item.get("explicit_lyrics"))
            rank = item.get("rank")
            if not isinstance(rank, int):
                rank = 0

            snippet_parts: list[str] = []
            if artist:
                snippet_parts.append(f"Artist: {artist}")
            if album:
                snippet_parts.append(f"Album: {album}")
            duration = _format_duration(duration_seconds)
            if duration:
                snippet_parts.append(f"Duration: {duration}")
            if explicit:
                snippet_parts.append("Explicit")
            if not snippet_parts:
                snippet_parts.append("Deezer track")
            snippet = " | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH]

            display_title = f"{title} · {artist}" if artist else title
            artist_obj = item.get("artist")
            album_obj = item.get("album")
            results.append(
                SearchResult(
                    title=display_title,
                    url=url,
                    snippet=snippet,
                    source="deezer.com",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "track_id": item.get("id"),
                        "artist": artist,
                        "artist_id": (
                            artist_obj.get("id")
                            if isinstance(artist_obj, dict)
                            else None
                        ),
                        "artist_url": (
                            _string(artist_obj.get("link"))
                            if isinstance(artist_obj, dict)
                            else ""
                        ),
                        "album": album,
                        "album_id": (
                            album_obj.get("id") if isinstance(album_obj, dict) else None
                        ),
                        "album_cover": (
                            _string(album_obj.get("cover_medium"))
                            if isinstance(album_obj, dict)
                            else ""
                        ),
                        "duration_seconds": duration_seconds,
                        "preview_url": _string(item.get("preview")),
                        "explicit_lyrics": explicit,
                        "deezer_rank": rank,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the Deezer catalog for tracks matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        request_params = {"q": query, "limit": str(limit)}
        async with self._client() as client:
            resp = await client.get(_API_SEARCH_URL, params=request_params)
            resp.raise_for_status()
            data = resp.json()
        return self._parse(data, limit=limit)
