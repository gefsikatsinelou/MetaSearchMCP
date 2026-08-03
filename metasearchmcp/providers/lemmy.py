"""Lemmy federated link aggregator search via the public API."""

from __future__ import annotations

from typing import Any, ClassVar

from bs4 import BeautifulSoup

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_DEFAULT_INSTANCE = "https://lemmy.world"
_SEARCH_PATH = "/api/v3/search"
_MAX_API_RESULTS = 20
_MAX_BODY_PREVIEW = 300


class LemmyProvider(BaseProvider):
    """Lemmy federated link aggregator search via the public API.

    Searches public posts across the Lemmy federation. No authentication required.
    """

    name = "lemmy"
    description = "Search public posts and discussions across the Lemmy fediverse."
    tags: ClassVar[list[str]] = ["social", "web", "news"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Lemmy posts for *query* via the public API."""
        qp = {
            "q": query,
            "type_": "Posts",
            "limit": min(params.num_results, self._max_results, _MAX_API_RESULTS),
            "sort": "TopAll",
        }

        async with self._client() as client:
            resp = await client.get(
                f"{_DEFAULT_INSTANCE}{_SEARCH_PATH}",
                params=qp,
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the API response into structured search results."""
        results: list[SearchResult] = []
        posts = data.get("posts", [])

        for i, item in enumerate(posts, start=1):
            post = item.get("post", {})
            creator = item.get("creator", {})
            community = item.get("community", {})
            counts = item.get("counts", {})

            title = post.get("name", "")
            url = post.get("url") or post.get("ap_id", "")

            # Build a useful snippet from the post body
            body = (post.get("body") or "")[:_MAX_BODY_PREVIEW]
            if body:
                body = BeautifulSoup(body, "html.parser").get_text(separator=" ")
                body = body[:MAX_SNIPPET_LENGTH]

            community_name = community.get("name", "")
            username = creator.get("name", "")
            score = counts.get("score", 0)
            comments = counts.get("comments", 0)

            published = self._iso_date_prefix(post.get("published"))

            snippet_parts: list[str] = []
            if body:
                snippet_parts.append(body)
            else:
                snippet_parts.append(f"[link post from {community_name or 'unknown'}]")
            snippet_parts.append(f"Score: {score} | Comments: {comments}")

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(p for p in snippet_parts if p),
                    source=community_name or "lemmy",
                    rank=i,
                    provider=self.name,
                    published_date=published,
                    extra={
                        "community": community_name,
                        "username": username,
                        "score": score,
                        "comments": comments,
                        "nsfw": post.get("nsfw", False),
                    },
                ),
            )

        return ProviderResult(results=results)
