from __future__ import annotations

from bs4 import BeautifulSoup

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_SEARCH_URL = "https://www.ecosia.org/search"


class EcosiaProvider(BaseProvider):
    """Ecosia search via HTML scraping.

    Ecosia uses Bing results under the hood. Since it routes through Bing,
    it inherits Bing's CAPTCHA behaviour on datacenter IPs and is likely to
    return 0 results in cloud or CI environments.
    Note: HTML structure may change without notice; parser is best-effort.
    """

    name = "ecosia"
    description = "Eco-friendly web search via Ecosia, powered by Bing."
    tags = ["web", "privacy"]

    def is_available(self) -> bool:
        return get_settings().allow_unstable_providers

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        qp = {
            "q": query,
            "p": 0,
        }

        async with self._scraper_client() as client:
            resp = await client.get(_SEARCH_URL, params=qp)
            resp.raise_for_status()

        return self._parse(resp.text)

    def _parse(self, html: str) -> ProviderResult:
        soup = BeautifulSoup(html, "lxml")
        results: list[SearchResult] = []

        # Ecosia results: article.result or div.result--web
        containers = (
            soup.select("article.result")
            or soup.select("div.result--web")
            or soup.select(".web-result")
        )

        for i, block in enumerate(containers, start=1):
            a = (
                block.select_one("a.result-title")
                or block.select_one("h2 a")
                or block.select_one("a[data-result-index]")
            )
            if not a:
                # fallback: first <a> with href
                for tag in block.find_all("a", href=True):
                    if tag.get("href", "").startswith("http"):
                        a = tag
                        break
            if not a:
                continue

            title = a.get_text(strip=True)
            url = a.get("href", "")
            if not url.startswith("http"):
                continue

            snippet = ""
            for sel in ("p.result-snippet", ".result-description", "p.result-body"):
                el = block.select_one(sel)
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
            if i >= self._max_results:
                break

        return ProviderResult(results=results)
