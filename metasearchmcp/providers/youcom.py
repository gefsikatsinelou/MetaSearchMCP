"""You.com Search API provider."""

from __future__ import annotations

from typing import ClassVar

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://ydc-index.io/v1/search"


class YouComProvider(BaseProvider):
    """You.com web search provider.

    API key optional for the Search API free tier. Configure ``YDC_API_KEY`` to
    send authenticated requests.
    """

    name = "youcom"
    description = "You.com web search API with optional citations and news results."
    tags: ClassVar[list[str]] = ["web"]

    def __init__(self) -> None:
        """Initialize You.com provider with API key from settings."""
        super().__init__()
        self._api_key = get_settings().ydc_api_key

    def is_available(self) -> bool:
        """Return True when a You.com API key is configured."""
        return bool(self._api_key)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search You.com for *query* via the official Search API."""
        qp = {
            "query": query,
            "count": str(min(params.num_results, self._max_results)),
        }
        if not params.safe_search:
            qp["safesearch"] = "off"
        headers = {
            "Accept": "application/json",
            "X-API-Key": self._api_key,
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return self._parse(data)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []
        sections = [
            data.get("results", {}).get("web", []),
            data.get("results", {}).get("news", []),
        ]
        rank = 1
        for items in sections:
            for item in items:
                url = item.get("url", "")
                title = item.get("title", "")
                snippet = item.get("description", "") or ""
                if not snippet:
                    snippets = item.get("snippets") or []
                    if snippets:
                        snippet = snippets[0]
                results.append(
                    SearchResult(
                        title=title,
                        url=url,
                        snippet=snippet,
                        rank=rank,
                        provider=self.name,
                        published_date=(item.get("page_age") or "")[0:10] or None,
                        extra={
                            "snippets": item.get("snippets", []),
                            "thumbnail_url": item.get("thumbnail_url", ""),
                            "favicon_url": item.get("favicon_url", ""),
                        },
                    ),
                )
                rank += 1
                if len(results) >= self._max_results:
                    return ProviderResult(results=results)
        return ProviderResult(results=results)
