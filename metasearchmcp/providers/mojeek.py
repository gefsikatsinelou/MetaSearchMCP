"""Mojeek independent web search via HTML scraping."""

from __future__ import annotations

from typing import ClassVar

from bs4 import BeautifulSoup

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_SEARCH_URL = "https://www.mojeek.com/search"
_MAX_API_RESULTS = 30


class MojeekProvider(BaseProvider):
    """Mojeek independent web search via HTML scraping.

    Mojeek crawls the web independently (not a meta-search of Google/Bing).
    No authentication required.
    Note: HTML structure may change without notice; parser is best-effort.
    """

    name = "mojeek"
    description = "Independent web search via Mojeek own crawler index."
    tags: ClassVar[list[str]] = ["web", "privacy"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Mojeek for *query* and return web results."""
        max_results = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        qp = {
            "q": query,
            "s": max_results,
            "lb": self._language_code(params.language),
        }

        async with self._scraper_client() as client:
            resp = await client.get(_SEARCH_URL, params=qp)
            resp.raise_for_status()

        return self._parse(resp.text, max_results=max_results)

    def _parse(self, html: str, max_results: int | None = None) -> ProviderResult:
        soup = BeautifulSoup(html, "lxml")
        results: list[SearchResult] = []
        limit = max_results or self._max_results

        # Mojeek: ul.results-standard > li, or ul.results > li
        items = soup.select("ul.results-standard li") or soup.select("ul.results li")

        for i, li in enumerate(items, start=1):
            a = (
                li.select_one("a.title")
                or li.select_one("h2 a")
                or li.select_one("a[href]")
            )
            if not a:
                continue
            title = a.get_text(strip=True)
            url = a.get("href", "")
            if not url.startswith("http"):
                continue

            snippet = ""
            for sel in ("p.s", "p.f", ".result-snippet", "p"):
                el = li.select_one(sel)
                if el:
                    snippet = el.get_text(strip=True)
                    break

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    rank=i,
                    provider=self.name,
                ),
            )
            if i >= limit:
                break

        return ProviderResult(results=results)
