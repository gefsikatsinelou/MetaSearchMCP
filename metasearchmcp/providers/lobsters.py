"""Lobste.rs tech-focused link aggregator search via the public JSON API.

Lobste.rs is a curated, invite-only community focused on computing and
technology discussion. The search API is public and requires no authentication.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://lobste.rs/search.json"
_MAX_API_RESULTS = 25


class LobstersProvider(BaseProvider):
    """Lobste.rs tech news and discussion search via the public JSON API.

    No authentication required for public search.
    Rate limit: considerate use recommended (community-run service).
    """

    name = "lobsters"
    description = "Search Lobste.rs — curated tech news and community discussion."
    tags: ClassVar[list[str]] = ["news", "tech", "social"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Lobste.rs stories for *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={
                    "q": query,
                    "what": "stories",
                    "order": "relevance",
                    "page": "1",
                },
            )
            resp.raise_for_status()
            data: list[dict[str, Any]] = resp.json()

        return self._parse(data, limit)

    @staticmethod
    def _format_tag_list(tags: list[str]) -> str:
        """Format story tags into a comma-separated string."""
        if not tags:
            return ""
        return ", ".join(tags[:8])

    def _parse(self, data: list[dict[str, Any]], limit: int) -> ProviderResult:
        """Parse the Lobste.rs JSON response into structured search results."""
        results: list[SearchResult] = []

        for i, item in enumerate(data[:limit], start=1):
            title = item.get("title", "")
            # Lobste.rs stories link to external URLs; use comments_url as fallback
            url = item.get("url") or item.get("comments_url", "")
            description = item.get("description", "") or ""
            tags = item.get("tags", []) or []
            score = item.get("score", 0)
            comment_count = item.get("comment_count", 0)
            submitter = item.get("submitter_user", "")
            created = self._iso_date_prefix(item.get("created_at"))

            snippet_parts = [description]
            if submitter:
                snippet_parts.append(f"by {submitter}")
            if tags:
                snippet_parts.append(f"Tags: {self._format_tag_list(tags)}")
            if score:
                snippet_parts.append(f"Score: {score}")
            if comment_count:
                snippet_parts.append(f"Comments: {comment_count}")

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(p for p in snippet_parts if p),
                    source="lobste.rs",
                    rank=i,
                    provider=self.name,
                    published_date=created,
                    extra={
                        "short_id": item.get("short_id"),
                        "comments_url": item.get("comments_url"),
                        "score": score,
                        "comment_count": comment_count,
                        "submitter": submitter,
                        "tags": tags,
                    },
                ),
            )

        return ProviderResult(results=results)
