"""Codeberg repository search via the public Gitea-compatible REST API.

Codeberg is a non-profit, community-driven Git hosting platform for
free and open-source software.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://codeberg.org/api/v1/repos/search"
_MAX_API_RESULTS = 30


class CodebergProvider(BaseProvider):
    """Codeberg repository search via the public REST API.

    No authentication required for public repository search.
    Rate limit: 200 requests per hour (unauthenticated).
    """

    name = "codeberg"
    description = "Search Codeberg repositories — free and open-source Git hosting."
    tags: ClassVar[list[str]] = ["code", "repos"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Codeberg repositories for *query*."""
        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={
                    "q": query,
                    "limit": str(
                        min(params.num_results, self._max_results, _MAX_API_RESULTS),
                    ),
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    @staticmethod
    def _format_topics(topics: list[str] | None) -> str:
        """Format topic list into a human-readable string."""
        if not topics:
            return ""
        return ", ".join(topics[:8])

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the Codeberg API response into structured search results."""
        results: list[SearchResult] = []

        for i, item in enumerate(data.get("data", []), start=1):
            name = item.get("full_name") or item.get("name", "")
            url = item.get("html_url", "")
            description = item.get("description") or ""
            topics = item.get("topics") or []
            stars = item.get("stars_count", 0)
            forks = item.get("forks_count", 0)
            language = item.get("language") or ""
            updated = self._iso_date_prefix(item.get("updated_at"))

            snippet_parts = [description]
            if language:
                snippet_parts.append(f"Language: {language}")
            if topics:
                snippet_parts.append(f"Topics: {self._format_topics(topics)}")
            if stars:
                snippet_parts.append(f"Stars: {stars}")

            results.append(
                SearchResult(
                    title=name,
                    url=url,
                    snippet=" | ".join(p for p in snippet_parts if p),
                    source="codeberg.org",
                    rank=i,
                    provider=self.name,
                    published_date=updated,
                    extra={
                        "stars": stars,
                        "forks": forks,
                        "language": language,
                        "topics": topics,
                        "clone_url": item.get("clone_url"),
                        "ssh_url": item.get("ssh_url"),
                    },
                ),
            )

        return ProviderResult(results=results)
