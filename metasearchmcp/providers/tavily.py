from __future__ import annotations

from tavily import AsyncTavilyClient

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider


class TavilyProvider(BaseProvider):
    """Tavily Search via the official Python SDK.

    Free tier: 1000 API credits/month. API key required.
    Sign up at https://app.tavily.com
    """

    name = "tavily"
    tags = ["web"]

    def __init__(self) -> None:
        super().__init__()
        self._api_key = get_settings().tavily_api_key
        if self._api_key:
            self._client = AsyncTavilyClient(api_key=self._api_key)

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        max_results = min(params.num_results, self._max_results, 20)

        # Note: Tavily's search API does not support language, country, or
        # safe_search filtering. These SearchParams fields are silently ignored.
        response = await self._client.search(
            query=query,
            max_results=max_results,
            search_depth="basic",
        )

        return self._parse(response)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []

        for i, item in enumerate(data.get("results", []), start=1):
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
                rank=i,
                provider=self.name,
                published_date=item.get("published_date"),
            ))

        return ProviderResult(results=results)
