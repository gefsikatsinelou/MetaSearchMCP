"""Audius music search via the official keyless public API.

Audius is a decentralised music-streaming platform whose public
discovery API requires no API key or OAuth token:

``GET https://api.audius.co/v1/tracks/search?query=QUERY&app_name=APP``

The endpoint returns artist-uploaded tracks ranked by relevance.  Each
hit carries the track title, the artist display name and handle, genre,
mood, duration, play/favourite/repost counts, cover art and — when the
artist allows streaming — a direct MP3 stream URL that an agent can
hand to an audio client.

Audius complements the licensed-catalogue providers (Deezer, iTunes)
and the metadata providers (MusicBrainz, Discogs) by exposing an
independent, artist-uploaded catalogue that those sources do not index.

Every request must carry an ``app_name`` value; the public discovery
node accepts any non-empty string without a key.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_BASE_URL = "https://api.audius.co/v1"
_API_SEARCH_URL = f"{_API_BASE_URL}/tracks/search"
_APP_NAME = "MetaSearchMCP"
_MAX_API_RESULTS = 50
_ARTWORK_KEYS = ("480x480", "150x150", "1000x1000")
# Audius descriptions can be long; keep the snippet part short.
_MAX_DESCRIPTION_SNIPPET = 200


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _string(value: object) -> str:
    """Return a cleaned string, or ``""`` for non-string values."""
    return _clean(value) if isinstance(value, str) else ""


def _int(value: object) -> int:
    """Return *value* as an int, or ``0`` for non-numeric input."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _as_dict(value: object) -> dict[str, Any]:
    """Return *value* when it is a mapping, otherwise an empty dict."""
    return value if isinstance(value, dict) else {}


def _format_duration(total_seconds: int) -> str:
    """Format a duration in seconds as ``M:SS`` (or ``H:MM:SS``)."""
    if total_seconds <= 0:
        return ""
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


class AudiusProvider(BaseProvider):
    """Search artist-uploaded tracks on the Audius music platform.

    Keyless. Uses the official Audius public search API, which covers the
    independent/artist-uploaded catalogue rather than the licensed-label
    catalogues served by Deezer or iTunes.  Hits are ordered by Audius's
    relevance ranking; each hit carries the artist, genre, mood, duration
    and counters, plus a direct stream URL when the track is streamable.
    """

    name = "audius"
    description = (
        "Search independent, artist-uploaded music tracks on Audius "
        "(artist/genre/duration/stream URL), no API key required."
    )
    tags: ClassVar[list[str]] = ["music", "media", "web"]

    @staticmethod
    def _track_url(item: dict[str, Any]) -> str:
        """Return the canonical audius.co page URL for a track hit."""
        permalink = _string(item.get("permalink"))
        if permalink:
            return f"https://audius.co/{permalink.lstrip('/')}"
        handle = _string(_as_dict(item.get("user")).get("handle"))
        slug = _string(item.get("slug"))
        if handle and slug:
            return f"https://audius.co/{handle}/{slug}"
        return ""

    @staticmethod
    def _stream_url(track_id: object, streamable: bool) -> str:
        """Return a direct MP3 stream URL when the track is streamable."""
        if streamable and isinstance(track_id, str) and track_id:
            return f"{_API_BASE_URL}/tracks/{track_id}/stream?app_name={_APP_NAME}"
        return ""

    @staticmethod
    def _artwork_url(item: dict[str, Any]) -> str:
        """Return the best available cover-art URL for a track hit."""
        artwork = _as_dict(item.get("artwork"))
        for key in _ARTWORK_KEYS:
            url = _string(artwork.get(key))
            if url:
                return url
        return ""

    @staticmethod
    def _tag_list(item: dict[str, Any]) -> list[str]:
        """Return the track's comma-separated tags as a clean string list."""
        raw = _string(item.get("tags"))
        return [tag for tag in (part.strip() for part in raw.split(",")) if tag]

    def _parse(self, data: Any, limit: int | None = None) -> ProviderResult:
        """Parse an Audius track-search response into structured results."""
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
            url = self._track_url(item)
            if not title or not url:
                continue

            user = _as_dict(item.get("user"))
            artist = _string(user.get("name")) or _string(user.get("handle"))
            handle = _string(user.get("handle"))
            genre = _string(item.get("genre"))
            mood = _string(item.get("mood"))
            duration_seconds = _int(item.get("duration"))
            play_count = _int(item.get("play_count"))
            favorite_count = _int(item.get("favorite_count"))
            repost_count = _int(item.get("repost_count"))
            streamable = bool(item.get("is_streamable"))
            tags = self._tag_list(item)

            snippet_parts: list[str] = []
            description = _string(item.get("description"))
            if description:
                snippet_parts.append(description[:_MAX_DESCRIPTION_SNIPPET])
            if artist:
                snippet_parts.append(f"Artist: {artist}")
            if genre:
                snippet_parts.append(f"Genre: {genre}")
            if mood:
                snippet_parts.append(f"Mood: {mood}")
            duration = _format_duration(duration_seconds)
            if duration:
                snippet_parts.append(f"Duration: {duration}")
            if play_count:
                snippet_parts.append(f"Plays: {play_count:,}")
            if not snippet_parts:
                snippet_parts.append("Audius track")
            snippet = " | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH]

            display_title = f"{title} · {artist}" if artist else title
            permalink = _string(item.get("permalink"))
            results.append(
                SearchResult(
                    title=display_title,
                    url=url,
                    snippet=snippet,
                    source="audius.co",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=self._iso_date_prefix(
                        _string(item.get("release_date"))
                    ),
                    extra={
                        "track_id": item.get("id"),
                        "numeric_id": item.get("track_id"),
                        "artist": artist,
                        "artist_handle": handle,
                        "artist_id": user.get("id"),
                        "genre": genre,
                        "mood": mood,
                        "duration_seconds": duration_seconds,
                        "play_count": play_count,
                        "favorite_count": favorite_count,
                        "repost_count": repost_count,
                        "tags": tags,
                        "artwork_url": self._artwork_url(item),
                        "stream_url": self._stream_url(item.get("id"), streamable),
                        "is_streamable": streamable,
                        "permalink": permalink,
                        "is_downloadable": bool(item.get("is_downloadable")),
                        "license": _string(item.get("license")),
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the Audius catalogue for tracks matching *query*."""
        if not query.strip():
            return ProviderResult(results=[])
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        request_params = {
            "query": query,
            "app_name": _APP_NAME,
            "limit": str(limit),
        }
        async with self._client() as client:
            resp = await client.get(_API_SEARCH_URL, params=request_params)
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError:
                # Discovery nodes may answer with an HTML error/maintenance page.
                return ProviderResult(results=[])
        return self._parse(data, limit=limit)
