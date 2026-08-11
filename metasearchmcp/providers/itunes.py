"""iTunes Search API provider for podcasts and media.

The Apple iTunes Search API is a public, keyless JSON endpoint that
searches podcasts, music, audiobooks, movies, and TV shows:

``GET https://itunes.apple.com/search?term=QUERY&media=podcast&limit=N``

This provider searches podcasts by default (the category missing from
the existing media providers). Each hit includes the show title, its
iTunes page URL, the author, genre, RSS feed URL, artwork, and the
most recent episode date.

No API key or authentication is required; parsing uses the standard
library plus the shared httpx client from the base provider.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://itunes.apple.com/search"
# iTunes caps a single request at 200 results; keep well below that.
_MAX_API_RESULTS = 50


class ITunesProvider(BaseProvider):
    """Search podcasts via the keyless Apple iTunes Search API."""

    name = "itunes"
    description = (
        "Search podcasts and other media via the Apple iTunes Search API, "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["podcast", "media", "music"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search iTunes podcasts for *query* and return structured results."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload: dict[str, str] = {
            "term": query,
            "media": "podcast",
            "limit": str(limit),
        }
        country = self.country_code(params.country)
        if country:
            payload["country"] = country

        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the API response into structured search results."""
        results: list[SearchResult] = []
        for i, item in enumerate(data.get("results", []), start=1):
            if not isinstance(item, dict):
                continue
            title = item.get("collectionName") or item.get("trackName") or ""
            url = item.get("collectionViewUrl") or item.get("trackViewUrl") or ""
            if not title or not url:
                continue

            artist = item.get("artistName") or ""
            genre = item.get("primaryGenreName") or ""
            snippet_parts = [part for part in (artist, genre) if part]
            snippet = " · ".join(snippet_parts)

            extra: dict[str, Any] = {}
            if artist:
                extra["artist"] = artist
            if genre:
                extra["genre"] = genre
            feed_url = item.get("feedUrl")
            if feed_url:
                extra["feed_url"] = feed_url
            artwork = item.get("artworkUrl100")
            if artwork:
                extra["artwork_url"] = artwork
            track_count = item.get("trackCount")
            if isinstance(track_count, int):
                extra["episode_count"] = track_count
            content_rating = item.get("contentAdvisoryRating")
            if content_rating:
                extra["content_rating"] = content_rating

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source="podcasts.apple.com",
                    rank=i,
                    provider=self.name,
                    published_date=self._iso_date_prefix(item.get("releaseDate")),
                    extra=extra,
                ),
            )

        return ProviderResult(results=results)
