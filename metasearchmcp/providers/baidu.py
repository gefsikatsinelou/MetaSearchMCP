from __future__ import annotations

from bs4 import BeautifulSoup

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider

_SEARCH_URL = "https://www.baidu.com/s"


class BaiduProvider(BaseProvider):
    """Baidu web search via HTML scraping.

    Suitable for Chinese-language and China-region queries.
    Baidu has aggressive anti-bot detection; results in automated contexts
    may be limited or blocked. Best-effort.
    Note: HTML structure may change without notice; parser is best-effort.
    """

    name = "baidu"
    tags = ["web"]

    def is_available(self) -> bool:
        return get_settings().allow_unstable_providers

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        qp = {
            "wd": query,
            "rn": min(params.num_results, self._max_results, 10),
            "ie": "utf-8",
        }

        async with self._scraper_client() as client:
            resp = await client.get(_SEARCH_URL, params=qp)
            resp.raise_for_status()

        return self._parse(resp.text)

    def _parse(self, html: str) -> ProviderResult:
        soup = BeautifulSoup(html, "lxml")
        results: list[SearchResult] = []

        # Baidu wraps results in div.result or div.c-result
        containers = soup.select("div.result") or soup.select("div[class*='result']")

        for block in containers:
            # Skip ads (class contains 'c-result-ad' or tpl contains 'ad')
            cls = " ".join(block.get("class", []))
            if "ad" in cls or "promote" in cls:
                continue

            a = block.select_one("h3 a") or block.select_one("h3.t a")
            if not a:
                continue

            title = a.get_text(strip=True)
            url = a.get("href", "")
            # Baidu wraps URLs in a redirect — accept as-is; resolving requires extra requests
            if not url.startswith("http"):
                continue

            snippet = ""
            for sel in (
                "div.c-abstract",
                "span.content-right_8Zs40",
                ".c-span18",
                ".c-span-last",
            ):
                el = block.select_one(sel)
                if el:
                    snippet = el.get_text(strip=True)[:400]
                    break

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    rank=len(results) + 1,
                    provider=self.name,
                )
            )
            if len(results) >= self._max_results:
                break

        return ProviderResult(results=results)
