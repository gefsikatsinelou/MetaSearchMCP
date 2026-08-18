"""Dailymotion video search via the public, keyless REST API.

Dailymotion exposes an unauthenticated JSON API for searching videos:

``GET https://api.dailymotion.com/videos?search=QUERY&fields=...&limit=N``

Each hit includes the video title, watch URL, uploader channel,
duration, view count, publication date, and a thumbnail URL.

No API key or authentication is required; parsing uses the standard
library plus the shared httpx client from the base provider.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.dailymotion.com/videos"
# The API returns at most 100 items per request; we cap lower for safety.
_MAX_API_RESULTS = 30
# Request only the fields we use to keep the response payload small.
_FIELDS = (
    "id,title,url,description,duration,created_time,"
    "owner.screenname,thumbnail_360_url,views_total"
)


class DailymotionProvider(BaseProvider):
    """Search videos across Dailymotion via the public JSON API.

    Uses the keyless REST API — no API key or authentication needed.
    Each hit carries the title, watch URL, uploader, duration, view
    count, publication date, and a thumbnail URL.
    """

    name = "dailymotion"
    description = (
        "Search videos across Dailymotion via the public API, no key required."
    )
    tags: ClassVar[list[str]] = ["video", "media"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Dailymotion videos for *query* via the public REST API."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {
            "search": query,
            "fields": _FIELDS,
            "limit": str(limit),
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    @staticmethod
    def _format_duration(seconds: object) -> str:
        """Format a duration in seconds as ``MM:SS`` or ``H:MM:SS``."""
        if not seconds:
            return ""
        try:
            total = int(seconds)
        except (TypeError, ValueError):
            return ""
        if total <= 0:
            return ""
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text description field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _published_date(created_time: object) -> str | None:
        """Convert a Unix timestamp to a YYYY-MM-DD date prefix."""
        if not created_time:
            return None
        try:
            return datetime.fromtimestamp(int(created_time), tz=UTC).date().isoformat()
        except (TypeError, ValueError, OverflowError, OSError):
            return None

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the Dailymotion API response into structured search results."""
        results: list[SearchResult] = []
        videos = data.get("list") or []

        for i, video in enumerate(videos, start=1):
            url = video.get("url", "")
            title = video.get("title", "")
            if not url or not title:
                continue

            description = self._clean_text(video.get("description"))
            duration = self._format_duration(video.get("duration"))
            views = video.get("views_total", 0)
            owner = video.get("owner.screenname", "")

            snippet_parts: list[str] = []
            if description:
                snippet_parts.append(description[:MAX_SNIPPET_LENGTH])
            meta_parts: list[str] = []
            if duration:
                meta_parts.append(f"Duration: {duration}")
            if views:
                meta_parts.append(f"Views: {views}")
            if owner:
                meta_parts.append(f"By: {owner}")
            if meta_parts:
                snippet_parts.append(" | ".join(meta_parts))

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(snippet_parts),
                    source="dailymotion.com",
                    rank=i,
                    provider=self.name,
                    published_date=self._published_date(video.get("created_time")),
                    extra={
                        "video_id": video.get("id", ""),
                        "owner": owner,
                        "thumbnail_url": video.get("thumbnail_360_url", ""),
                        "duration_seconds": video.get("duration"),
                        "duration": duration,
                        "views": views,
                    },
                ),
            )

        return ProviderResult(results=results)
