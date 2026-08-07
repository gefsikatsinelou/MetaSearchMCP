"""Bluesky social post search via the public, keyless AppView API.

Bluesky (bsky.app) exposes an unauthenticated search endpoint on its public
AppView: ``https://api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=QUERY``.
It returns recent public posts matching the query, each with the post text,
author handle/display name, creation date, and interaction counts
(like/repost/reply/bookmark).

No API key or authentication is required for public search; parsing uses only
the shared httpx client from the base provider.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"
# The AppView returns up to 100 posts per page; we cap client-side.
_MAX_API_RESULTS = 50
_PROFILE_BASE = "https://bsky.app/profile"


class BlueskyProvider(BaseProvider):
    """Search recent public posts on Bluesky via the keyless AppView API.

    Each hit carries the post text, author handle, a creation date, and
    like/repost/reply counts. Post URLs point at the bsky.app web client.
    """

    name = "bluesky"
    description = "Search recent public posts and discussions on Bluesky."
    tags: ClassVar[list[str]] = ["social", "web"]

    @staticmethod
    def _date_prefix(created_at: str | None) -> str | None:
        """Convert an API ISO-8601 timestamp to a YYYY-MM-DD prefix."""
        if not created_at:
            return None
        try:
            return (
                datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                .astimezone(UTC)
                .date()
                .isoformat()
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _post_url(uri: str, handle: str) -> str:
        """Build a bsky.app web URL from an at:// post URI and author handle."""
        if not uri:
            return ""
        parts = uri.split("/")
        rkey = parts[-1] if len(parts) > 1 else ""
        if not rkey or not handle:
            return ""
        return f"{_PROFILE_BASE}/{handle}/post/{rkey}"

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the searchPosts response into structured results."""
        results: list[SearchResult] = []
        posts = data.get("posts") or []

        for i, post in enumerate(posts, start=1):
            if not isinstance(post, dict):
                continue
            uri = post.get("uri", "")
            author = post.get("author") or {}
            handle = author.get("handle") or ""
            display_name = author.get("displayName") or handle or ""
            url = self._post_url(uri, handle)
            if not url:
                continue

            record = post.get("record") or {}
            if not isinstance(record, dict):
                record = {}
            text = record.get("text") or ""
            text = " ".join(str(text).split())

            title = f"{display_name}: {text[:80]}" if text else display_name
            snippet = text[:MAX_SNIPPET_LENGTH]

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source="bsky.app",
                    rank=i,
                    provider=self.name,
                    published_date=self._date_prefix(record.get("createdAt")),
                    extra={
                        "handle": handle,
                        "display_name": display_name,
                        "author_did": author.get("did") or "",
                        "likes": post.get("likeCount", 0),
                        "reposts": post.get("repostCount", 0),
                        "replies": post.get("replyCount", 0),
                        "bookmarks": post.get("bookmarkCount", 0),
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Bluesky public posts for *query* via the AppView API."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        qp = {
            "q": query,
            "limit": limit,
        }
        async with self._client() as client:
            resp = await client.get(_SEARCH_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)
