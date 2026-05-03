from __future__ import annotations

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://hn.algolia.com/api/v1/search"


class HackerNewsProvider(BaseProvider):
    """Hacker News search via the Algolia HN API.

    Fully public, no authentication required. Returns stories and Ask HNs.
    """

    name = "hackernews"
    description = "Search Hacker News stories, comments, and discussions via Algolia."
    tags = ["web", "developer", "news"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        qp = {
            "query": query,
            "hitsPerPage": min(params.num_results, self._max_results, 30),
            "tags": "story",
        }

        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []

        for i, hit in enumerate(data.get("hits", []), start=1):
            title = hit.get("title", "")
            story_url = hit.get("url", "")
            hn_id = hit.get("objectID", "")
            hn_url = f"https://news.ycombinator.com/item?id={hn_id}"
            points = hit.get("points") or 0
            comments = hit.get("num_comments") or 0
            author = hit.get("author", "")
            created = (hit.get("created_at") or "")[:10]

            # Prefer the story URL; fall back to HN thread
            url = story_url if story_url else hn_url

            snippet_parts = []
            if story_url and story_url != url:
                snippet_parts.append(f"Discussion: {hn_url}")
            snippet_parts.append(
                f"Points: {points} | Comments: {comments} | By: {author}",
            )

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(snippet_parts),
                    source="news.ycombinator.com",
                    rank=i,
                    provider=self.name,
                    published_date=created or None,
                    extra={
                        "points": points,
                        "num_comments": comments,
                        "author": author,
                        "hn_url": hn_url,
                    },
                ),
            )

        return ProviderResult(results=results)
