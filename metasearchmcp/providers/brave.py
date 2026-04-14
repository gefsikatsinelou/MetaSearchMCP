from __future__ import annotations

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider

_API_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveProvider(BaseProvider):
    """Brave Search via the official Web Search API.

    Free tier: 2000 req/month. API key required.
    Sign up at https://brave.com/search/api/
    """

    name = "brave"
    tags = ["web", "privacy"]

    def __init__(self) -> None:
        super().__init__()
        self._api_key = get_settings().brave_api_key

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        qp = {
            "q": query,
            "count": str(min(params.num_results, self._max_results, 20)),
            "search_lang": params.language,
            "country": params.country.upper(),
        }
        if not params.safe_search:
            qp["safesearch"] = "off"

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self._api_key,
        }

        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []
        web = data.get("web", {})

        for i, item in enumerate(web.get("results", []), start=1):
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("description", ""),
                rank=i,
                provider=self.name,
                published_date=item.get("age"),
            ))

        return ProviderResult(results=results)
