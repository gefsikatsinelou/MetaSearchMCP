"""Stack Overflow / Stack Exchange search via the official API."""

from __future__ import annotations

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://api.stackexchange.com/2.3/search/advanced"
_MAX_API_RESULTS = 30


class StackOverflowProvider(BaseProvider):
    """Stack Overflow / Stack Exchange search via the official API.

    Public access: 300 req/day (IP-based).
    With a Stack Apps API key: 10,000 req/day.
    Set STACKEXCHANGE_API_KEY env var to increase quota.
    """

    name = "stackoverflow"
    description = "Search Stack Overflow questions and answers."
    tags = ["web", "code", "developer"]

    def __init__(self) -> None:
        super().__init__()
        settings = get_settings()
        self._api_key: str = getattr(settings, "stackexchange_api_key", "")

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Stack Overflow questions for *query*."""
        qp: dict = {
            "q": query,
            "site": "stackoverflow",
            "pagesize": min(params.num_results, self._max_results, _MAX_API_RESULTS),
            "order": "desc",
            "sort": "relevance",
            "filter": "default",
        }
        if self._api_key:
            qp["key"] = self._api_key

        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []

        for i, item in enumerate(data.get("items", []), start=1):
            tags = item.get("tags", [])
            answered = item.get("is_answered", False)
            score = item.get("score", 0)
            answer_count = item.get("answer_count", 0)

            snippet_parts = [f"Tags: {', '.join(tags)}"] if tags else []
            snippet_parts.append(f"Score: {score} | Answers: {answer_count}")
            if answered:
                snippet_parts.append("(answered)")

            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("link", ""),
                    snippet=" | ".join(snippet_parts),
                    source="stackoverflow.com",
                    rank=i,
                    provider=self.name,
                    published_date=None,
                    extra={
                        "score": score,
                        "answer_count": answer_count,
                        "is_answered": answered,
                        "tags": tags,
                    },
                ),
            )

        return ProviderResult(results=results)
