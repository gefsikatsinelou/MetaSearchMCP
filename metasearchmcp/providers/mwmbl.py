"""Mwmbl — non-profit, open-source web search engine."""

from __future__ import annotations

from typing import ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://api.mwmbl.org/api/v1/search/"


class MwmblProvider(BaseProvider):
    """Mwmbl — non-profit, open-source web search engine.

    Public JSON API, no authentication required.
    """

    name = "mwmbl"
    description = "Non-commercial open-source web search via the Mwmbl community index."
    tags: ClassVar[list[str]] = ["web", "general"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Mwmbl for *query* and return web results."""
        max_results = min(params.num_results, self._max_results)
        async with self._client() as client:
            resp = await client.get(_API_URL, params={"s": query})
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, max_results)

    def _parse(self, data: list, max_results: int | None = None) -> ProviderResult:
        """Parse the API response into structured search results."""
        results: list[SearchResult] = []
        limit = max_results or self._max_results

        for i, item in enumerate(data, start=1):
            title_parts = [t["value"] for t in item.get("title", [])]
            extract_parts = item.get("extract", [])
            content = extract_parts[0]["value"] if extract_parts else ""
            results.append(
                SearchResult(
                    title="".join(title_parts),
                    url=item.get("url", ""),
                    snippet=content,
                    source="mwmbl.org",
                    rank=i,
                    provider=self.name,
                ),
            )
            if i >= limit:
                break

        return ProviderResult(results=results)
