from __future__ import annotations

from bs4 import BeautifulSoup

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from metasearchmcp.providers.base import BaseProvider

_SEARCH_URL = "https://yandex.com/search/"


class YandexProvider(BaseProvider):
    """Yandex web search via HTML scraping.

    Yandex returns a mostly client-side-rendered response to non-browser
    requests; results are typically empty from datacenter IPs. May work on
    residential IPs or with a proxy that has established cookies.
    Note: HTML structure may change without notice; parser is best-effort.
    """

    name = "yandex"
    tags = ["web"]

    def is_available(self) -> bool:
        return get_settings().allow_unstable_providers

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        qp = {
            "text": query,
            "numdoc": min(params.num_results, self._max_results, 10),
            "lang": params.language,
        }

        async with self._scraper_client() as client:
            resp = await client.get(_SEARCH_URL, params=qp)
            resp.raise_for_status()

        return self._parse(resp.text)

    def _parse(self, html: str) -> ProviderResult:
        soup = BeautifulSoup(html, "lxml")
        results: list[SearchResult] = []

        # Yandex results: li.serp-item containing div.organic
        containers = soup.select("li.serp-item") or soup.select("div.Organic")

        for i, block in enumerate(containers, start=1):
            a = (
                block.select_one("a.OrganicTitle-Link")
                or block.select_one("a.organic__url")
                or block.select_one("h2 a")
            )
            if not a:
                continue
            title = a.get_text(strip=True)
            url = a.get("href", "")
            if not url.startswith("http"):
                continue

            snippet = ""
            for sel in (
                "div.OrganicTextContentSpan",
                "div.organic__content-wrapper",
                "div.text-container",
                ".Organic-ContentWrapper",
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
                    rank=i,
                    provider=self.name,
                ),
            )
            if i >= self._max_results:
                break

        return ProviderResult(results=results)
