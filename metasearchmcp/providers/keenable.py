"""Keenable web search via the official Search API."""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://api.keenable.ai/v1/search"
_MAX_API_RESULTS = 20
_SNIPPET_MAX_CHARS = 500


class KeenableProvider(BaseProvider):
    """Keenable web search via the official Search API.

    API key required. Sign up at https://keenable.ai/
    """

    name = "keenable"
    description = "Web search via the Keenable Search API."
    tags: ClassVar[list[str]] = ["web"]

    def __init__(self) -> None:
        """Initialize Keenable provider with API key from settings."""
        super().__init__()
        self._api_key = get_settings().keenable_api_key

    def is_available(self) -> bool:
        """Return True when a Keenable API key is configured."""
        return bool(self._api_key)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Keenable for *query*."""
        payload = {
            "query": query,
            "max_results": min(params.num_results, self._max_results, _MAX_API_RESULTS),
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-Key": self._api_key,
            "X-Keenable-Title": "MetaSearchMCP",
        }

        async with self._client() as client:
            resp = await client.post(_API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the API response into structured search results."""
        results: list[SearchResult] = []
        rank = 0
        for item in data.get("results") or []:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            rank += 1
            # Prefer the short description; fall back to a truncated page excerpt.
            snippet = (
                item.get("description")
                or (item.get("snippet") or "")[:_SNIPPET_MAX_CHARS]
            )
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item["url"],
                    snippet=snippet,
                    rank=rank,
                    provider=self.name,
                    published_date=None,
                ),
            )

        return ProviderResult(results=results)
