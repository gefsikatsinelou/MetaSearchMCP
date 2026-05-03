from __future__ import annotations

from bs4 import BeautifulSoup

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider

_SEARCH_URL = "https://www.mojeek.com/search"


class MojeekProvider(BaseProvider):
    """Mojeek independent web search via HTML scraping.

    Mojeek crawls the web independently (not a meta-search of Google/Bing).
    No authentication required.
    Note: HTML structure may change without notice; parser is best-effort.
    """

    name = "mojeek"
    description = "Independent web search via Mojeek own crawler index."
    tags = ["web", "privacy"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        qp = {
            "q": query,
            "s": min(params.num_results, self._max_results, 30),
            "lb": params.language,
        }

        async with self._scraper_client() as client:
            resp = await client.get(_SEARCH_URL, params=qp)
            resp.raise_for_status()

        return self._parse(resp.text)

    def _parse(self, html: str) -> ProviderResult:
        soup = BeautifulSoup(html, "lxml")
        results: list[SearchResult] = []

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
                )
            )
            if i >= self._max_results:
                break

        return ProviderResult(results=results)
