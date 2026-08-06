"""PeerTube federated video search via the public, keyless REST API.

PeerTube is a decentralized, federated video platform. The flagship
instance (peertube.tv) exposes a public REST API that searches videos
across the whole federation without requiring an API key:

``GET https://peertube.tv/api/v1/videos?search=QUERY&count=N``

Each hit includes the video title, watch URL, uploader channel,
duration, view/like counts, publication date, and a thumbnail URL.

No API key or authentication is required; parsing uses the standard
library plus the shared httpx client from the base provider.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://peertube.tv/api/v1/videos"
# Thumbnail paths returned by the API are relative to the instance origin.
_API_ORIGIN = "https://peertube.tv"
# PeerTube caps a single listing request at 100 items.
_MAX_API_RESULTS = 30


class PeerTubeProvider(BaseProvider):
    """Search federated videos across the PeerTube network.

    Uses the keyless REST API of the flagship instance (peertube.tv),
    which aggregates videos from all connected instances. Each hit
    carries the title, watch URL, uploader, duration, engagement
    counts, and a thumbnail URL.
    """

    name = "peertube"
    description = "Search federated videos across the PeerTube network."
    tags: ClassVar[list[str]] = ["video", "media"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search PeerTube videos for *query* via the public REST API."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {
            "search": query,
            "count": str(limit),
            "sort": "-publishedAt",
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    @staticmethod
    def _format_duration(seconds: Any) -> str:
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
    def _absolute_thumbnail(path: Any) -> str:
        """Prefix a relative thumbnail path with the API instance origin."""
        if not path:
            return ""
        value = str(path)
        if value.startswith("http"):
            return value
        return f"{_API_ORIGIN}{value}"

    @staticmethod
    def _clean_text(value: Any) -> str:
        """Collapse whitespace in a free-text description field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the PeerTube API response into structured search results."""
        results: list[SearchResult] = []
        videos = data.get("data") or []

        for i, video in enumerate(videos, start=1):
            url = video.get("url", "")
            if not url:
                continue

            title = video.get("name", "")
            description = self._clean_text(
                video.get("truncatedDescription") or video.get("description") or "",
            )
            duration = self._format_duration(video.get("duration"))
            views = video.get("views", 0)
            likes = video.get("likes", 0)

            snippet_parts: list[str] = []
            if description:
                snippet_parts.append(description[:MAX_SNIPPET_LENGTH])
            meta_parts: list[str] = []
            if duration:
                meta_parts.append(f"Duration: {duration}")
            if views:
                meta_parts.append(f"Views: {views}")
            if likes:
                meta_parts.append(f"Likes: {likes}")
            if meta_parts:
                snippet_parts.append(" | ".join(meta_parts))

            channel = video.get("channel") or {}
            account = video.get("account") or {}
            category = video.get("category") or {}
            language = video.get("language") or {}

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(snippet_parts),
                    source="peertube.tv",
                    rank=i,
                    provider=self.name,
                    published_date=self._iso_date_prefix(
                        video.get("publishedAt") or video.get("createdAt"),
                    ),
                    extra={
                        "channel": (
                            channel.get("displayName") or channel.get("name") or ""
                        ),
                        "channel_url": channel.get("url") or "",
                        "author": (
                            account.get("displayName") or account.get("name") or ""
                        ),
                        "author_url": account.get("url") or "",
                        "thumbnail_url": self._absolute_thumbnail(
                            video.get("thumbnailPath"),
                        ),
                        "duration_seconds": video.get("duration"),
                        "duration": duration,
                        "views": views,
                        "likes": likes,
                        "category": category.get("label") or "",
                        "language": language.get("label") or "",
                        "nsfw": bool(video.get("nsfw", False)),
                    },
                ),
            )

        return ProviderResult(results=results)
