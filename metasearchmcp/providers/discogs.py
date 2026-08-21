"""Discogs music database search via the public, keyless API.

Discogs is a large community-built database of music releases, artists,
and labels. Its public API supports unauthenticated database search:

``GET https://api.discogs.com/database/search?q=QUERY&type=release&per_page=N``

Each hit includes the release title, artist, year, label, format,
genre/style tags, and a cover image URL. The API is rate-limited
(60 requests/minute) but requires no key for basic search.

This provider searches releases by default; parsing uses only the shared
httpx client from the base provider.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://api.discogs.com/database/search"
# Discogs caps a single page at this many results.
_MAX_API_RESULTS = 50
# Keep the snippet readable: at most this many format/label entries.
_MAX_DISPLAY_ITEMS = 3


class DiscogsProvider(BaseProvider):
    """Search music releases in the Discogs database via the public API.

    Uses the keyless database search endpoint (60 requests/minute limit).
    Each hit carries the release title, artist, year, label, format,
    genre/style tags, and a cover image URL.
    """

    name = "discogs"
    description = (
        "Search music releases, artists and labels in the Discogs database, "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["music", "media", "web"]

    @staticmethod
    def _join(values: object, max_items: int = _MAX_DISPLAY_ITEMS) -> list[str]:
        """Return a list of clean string values, capped at *max_items*."""
        if not isinstance(values, list):
            return []
        cleaned = [str(v).strip() for v in values if str(v).strip()]
        return cleaned[:max_items]

    @staticmethod
    def _cover_url(item: dict[str, Any]) -> str:
        """Return the best available cover/thumbnail image URL."""
        for key in ("cover_image", "thumb"):
            value = item.get(key)
            if value:
                return str(value)
        return ""

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the Discogs search response into structured results."""
        results: list[SearchResult] = []
        for i, item in enumerate(data.get("results") or [], start=1):
            if not isinstance(item, dict):
                continue
            title = item.get("title") or ""
            uri = item.get("uri") or ""
            if not title or not uri:
                continue

            year = item.get("year") or ""
            genres = self._join(item.get("genre"))
            styles = self._join(item.get("style"))
            labels = self._join(item.get("label"))
            formats = self._join(item.get("format"))

            snippet_parts: list[str] = []
            if year:
                snippet_parts.append(f"Year: {year}")
            if genres:
                snippet_parts.append(f"Genre: {', '.join(genres)}")
            if styles:
                snippet_parts.append(f"Style: {', '.join(styles)}")
            if labels:
                snippet_parts.append(f"Label: {', '.join(labels)}")
            if formats:
                snippet_parts.append(f"Format: {', '.join(formats)}")

            cover = self._cover_url(item)
            extra: dict[str, Any] = {
                "type": item.get("type") or "",
                "year": year,
                "genres": genres,
                "styles": styles,
                "labels": labels,
                "formats": formats,
            }
            if cover:
                extra["image_url"] = cover

            results.append(
                SearchResult(
                    title=title,
                    url=f"https://www.discogs.com{uri}",
                    snippet=" | ".join(snippet_parts),
                    source="discogs.com",
                    rank=i,
                    provider=self.name,
                    published_date=str(year) if year else None,
                    extra=extra,
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Discogs releases for *query* via the public database API."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload: dict[str, str] = {
            "q": query,
            "type": "release",
            "per_page": str(limit),
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)
