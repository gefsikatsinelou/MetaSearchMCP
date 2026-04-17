from __future__ import annotations

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider

_API_URL = "https://rubygems.org/api/v1/search.json"


class RubyGemsProvider(BaseProvider):
    """RubyGems package search via the public API."""

    name = "rubygems"
    description = "Search Ruby gems on RubyGems.org."
    tags = ["web", "code", "developer", "packages"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        qp = {
            "query": query,
        }

        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data[: min(params.num_results, self._max_results, 20)])

    def _parse(self, data: list[dict]) -> ProviderResult:
        results: list[SearchResult] = []

        for i, item in enumerate(data, start=1):
            name = item.get("name", "")
            version = item.get("version", "")
            downloads = item.get("downloads", 0)
            authors = item.get("authors", "")
            info = item.get("info", "") or ""

            snippet_parts = [info]
            if version:
                snippet_parts.append(f"v{version}")
            if authors:
                snippet_parts.append(authors)
            snippet_parts.append(f"Downloads: {downloads:,}")

            results.append(
                SearchResult(
                    title=name,
                    url=f"https://rubygems.org/gems/{name}",
                    snippet=" | ".join(part for part in snippet_parts if part),
                    source="rubygems.org",
                    rank=i,
                    provider=self.name,
                    extra={
                        "version": version,
                        "authors": authors,
                        "downloads": downloads,
                    },
                )
            )

        return ProviderResult(results=results)
