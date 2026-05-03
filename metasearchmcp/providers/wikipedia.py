from __future__ import annotations

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://en.wikipedia.org/w/api.php"


class WikipediaProvider(BaseProvider):
    """Wikipedia full-text search via the MediaWiki Action API.

    No authentication required. Returns article summaries.
    """

    name = "wikipedia"
    description = "Search Wikipedia articles across all languages."
    tags = ["web", "academic", "knowledge"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        qp = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": str(min(params.num_results, self._max_results)),
            "srprop": "snippet|titlesnippet|timestamp",
            "format": "json",
            "utf8": "1",
        }

        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []
        items = data.get("query", {}).get("search", [])

        for i, item in enumerate(items, start=1):
            title = item.get("title", "")
            slug = title.replace(" ", "_")
            url = f"https://en.wikipedia.org/wiki/{slug}"
            # snippet contains HTML spans — strip them simply
            raw_snippet = item.get("snippet", "")
            snippet = BeautifulSoupStrip.strip(raw_snippet)

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source="en.wikipedia.org",
                    rank=i,
                    provider=self.name,
                    published_date=item.get("timestamp", "")[:10] or None,
                ),
            )

        return ProviderResult(results=results)


class BeautifulSoupStrip:
    """Minimal HTML tag stripper without importing bs4 for a single operation."""

    @staticmethod
    def strip(html: str) -> str:
        import re

        return re.sub(r"<[^>]+>", "", html).strip()
