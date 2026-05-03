from __future__ import annotations

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://api.mwmbl.org/api/v1/search/"


class MwmblProvider(BaseProvider):
    """Mwmbl — non-profit, open-source web search engine.

    Public JSON API, no authentication required.
    """

    name = "mwmbl"
    description = "Non-commercial open-source web search via the Mwmbl community index."
    tags = ["web", "general"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        async with self._client() as client:
            resp = await client.get(_API_URL, params={"s": query})
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: list) -> ProviderResult:
        results: list[SearchResult] = []

        for i, item in enumerate(data, start=1):
            title_parts = [t["value"] for t in item.get("title", [])]
            extract_parts = item.get("extract", [])
            content = extract_parts[0]["value"] if extract_parts else ""
            results.append(
                SearchResult(
                    title="".join(title_parts),
                    url=item["url"],
                    snippet=content,
                    source="mwmbl.org",
                    rank=i,
                    provider=self.name,
                ),
            )

        return ProviderResult(results=results)
