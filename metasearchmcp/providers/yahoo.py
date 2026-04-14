from __future__ import annotations

from bs4 import BeautifulSoup

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider

_SEARCH_URL = "https://search.yahoo.com/search"


class YahooProvider(BaseProvider):
    """Yahoo web search via HTML scraping.

    Yahoo frequently returns HTTP 500 errors from datacenter IPs due to
    bot detection. May work on residential IPs or with a proxy.
    Note: HTML structure may change without notice; parser is best-effort.
    """

    name = "yahoo"
    tags = ["web"]

    def is_available(self) -> bool:
        return get_settings().allow_unstable_providers

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        qp = {
            "p": query,
            "n": min(params.num_results, self._max_results, 10),
            "ei": "UTF-8",
        }

        async with self._scraper_client() as client:
            resp = await client.get(_SEARCH_URL, params=qp)
            if resp.status_code >= 500:
                raise RuntimeError(
                    f"Yahoo returned HTTP {resp.status_code}; request likely blocked upstream"
                )
            resp.raise_for_status()

        return self._parse(resp.text)

    def _parse(self, html: str) -> ProviderResult:
        soup = BeautifulSoup(html, "lxml")
        results: list[SearchResult] = []

        # Yahoo wraps results in div.algo or li inside #web
        containers = soup.select("div#web li") or soup.select("div.algo")

        for i, block in enumerate(containers, start=1):
            a = block.select_one("h3 a") or block.select_one("h2 a")
            if not a:
                continue
            title = a.get_text(strip=True)
            url = a.get("href", "")

            # Yahoo sometimes wraps real URL in a redirect — use as-is
            snippet = ""
            for sel in ("p.fz-ms", "div.compText p", "div.s p", ".compText span"):
                el = block.select_one(sel)
                if el:
                    snippet = el.get_text(strip=True)
                    break

            if not url or not title:
                continue

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
