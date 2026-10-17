"""Music lyrics search via the keyless LRCLIB public API.

LRCLIB (https://lrclib.net) is an open, community-maintained lyrics database
whose REST API is keyless:

``GET https://lrclib.net/api/search?q=QUERY``

The endpoint matches a free-text query against track titles and artist names
and returns a JSON array of records.  Each record carries the LRCLIB track id,
the track name, artist and album name, the track duration in seconds, whether
the track is instrumental, and whether synced (LRC) lyrics are available
alongside the plain-text lyrics.  Every hit links to its own LRCLIB track page
at ``https://lrclib.net/tracks/{id}``.

This complements the other music providers
(:mod:`metasearchmcp.providers.musicbrainz`, ``deezer``, ``audius`` and
``discogs``), which index recordings and release metadata but do not return
lyrics.
"""

from __future__ import annotations

from typing import ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://lrclib.net/api/search"
# LRCLIB returns its whole result set; keep pages small for agents.
_MAX_API_RESULTS = 50
# Maximum number of lyric characters previewed in a result snippet.
_MAX_LYRICS_IN_SNIPPET = 180
# Maximum number of lyric characters embedded in a result's ``extra`` payload.
_MAX_LYRICS_IN_EXTRA = 1500


class LrclibProvider(BaseProvider):
    """Search songs and their lyrics in the LRCLIB public lyrics database.

    Keyless.  Uses the public LRCLIB search API.  Each result carries the
    artist, album, duration, whether the track is instrumental, a preview of
    the plain-text lyrics and a link to the track's LRCLIB page, with the full
    plain lyrics included in the result's ``extra`` payload.
    """

    name = "lrclib"
    description = (
        "Search music tracks and lyrics (artist, album, duration, plain and "
        "synced lyrics) via the keyless LRCLIB API — no API key required."
    )
    tags: ClassVar[list[str]] = ["music", "media", "web"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if value is None:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _as_number(value: object) -> float | None:
        """Return *value* as a float when it is a real number, else ``None``."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    @classmethod
    def _duration(cls, value: object) -> float | None:
        """Return a positive track duration in seconds, else ``None``.

        LRCLIB reports an unknown duration as ``0``; treat that as unknown so
        callers never see a meaningless zero-length track.
        """
        seconds = cls._as_number(value)
        if seconds is None or seconds <= 0:
            return None
        return seconds

    @staticmethod
    def _duration_label(seconds: float | None) -> str:
        """Format a duration in seconds as ``m:ss`` (empty when unknown)."""
        if seconds is None or seconds <= 0:
            return ""
        total = round(seconds)
        return f"{total // 60}:{total % 60:02d}"

    @staticmethod
    def _title(track: str, artist: str) -> str:
        """Build a display title, avoiding a duplicated artist name."""
        if track and artist and artist.lower() not in track.lower():
            return f"{track} — {artist}"
        return track or artist

    def _parse(
        self,
        data: object,
        limit: int | None = None,
        query: str = "",
    ) -> ProviderResult:
        """Parse an LRCLIB search response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        # Used only when a record has no id to link to.
        fallback_url = f"https://lrclib.net/search/{quote(query)}" if query else ""

        for item in data:
            if not isinstance(item, dict):
                continue
            track = self._clean_text(item.get("trackName"))
            artist = self._clean_text(item.get("artistName"))
            title = self._title(track, artist)
            if not title:
                continue

            album = self._clean_text(item.get("albumName"))
            raw_id = item.get("id")
            track_id = (
                raw_id
                if isinstance(raw_id, int) and not isinstance(raw_id, bool)
                else None
            )
            duration = self._duration(item.get("duration"))
            duration_label = self._duration_label(duration)
            instrumental = bool(item.get("instrumental"))
            lyrics = self._clean_text(item.get("plainLyrics"))
            has_synced = bool(item.get("syncedLyrics"))

            snippet_parts: list[str] = []
            if artist:
                snippet_parts.append(f"Artist: {artist}")
            if album:
                snippet_parts.append(f"Album: {album}")
            if duration_label:
                snippet_parts.append(f"Duration: {duration_label}")
            if instrumental:
                snippet_parts.append("Instrumental")
            elif lyrics:
                preview = lyrics[:_MAX_LYRICS_IN_SNIPPET]
                if len(lyrics) > _MAX_LYRICS_IN_SNIPPET:
                    preview = f"{preview}…"
                snippet_parts.append(preview)

            url = (
                f"https://lrclib.net/tracks/{track_id}"
                if track_id is not None
                else fallback_url
            )
            if not url:
                continue

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source="lrclib.net",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "track_id": track_id,
                        "track": track,
                        "artist": artist,
                        "album": album,
                        "duration_seconds": duration,
                        "instrumental": instrumental,
                        "has_synced_lyrics": has_synced,
                        "plain_lyrics": lyrics[:_MAX_LYRICS_IN_EXTRA] or None,
                    },
                ),
            )
            if len(results) >= max_results:
                break

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search LRCLIB for songs and lyrics matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(_API_URL, params={"q": query})
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit, query=query)
