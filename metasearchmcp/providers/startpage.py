from __future__ import annotations

from bs4 import BeautifulSoup

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider

_SEARCH_URL = "https://www.startpage.com/sp/search"


class StartpageProvider(BaseProvider):
    """Startpage search via HTML scraping.

    Startpage proxies Google results with privacy preservation.
    Heavy anti-bot measures; this provider may be unreliable in automated
    contexts. Use as best-effort.
    Note: HTML structure may change without notice; parser is best-effort.
    """

    name = "startpage"
    tags = ["web", "privacy", "google"]

    def is_available(self) -> bool:
        return get_settings().allow_unstable_providers

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        form_data = {
            "query": query,
            "cat": "web",
            "pl": "ext-ff",
            "language": params.language,
        }

        async with self._scraper_client() as client:
            resp = await client.post(_SEARCH_URL, data=form_data)
            resp.raise_for_status()

        if (
            "Error 883" in resp.text
            or "ability to connect to Startpage has been suspended" in resp.text
        ):
            raise RuntimeError(
                "Startpage temporarily suspended requests from this network (Error 883)"
            )

        return self._parse(resp.text)

    def _parse(self, html: str) -> ProviderResult:
        soup = BeautifulSoup(html, "lxml")
        results: list[SearchResult] = []

        # Startpage uses CSS-in-JS class names that change; rely on stable
        # semantic classes: div.result, a.result-title / a.result-link, p.description
        containers = soup.select("div.result")

        for i, block in enumerate(containers, start=1):
            # Title + URL: a.result-title or a.result-link
            a = block.select_one("a.result-title") or block.select_one("a.result-link")
            if not a:
                # Fallback: first external <a> in the block
                a = block.find("a", href=lambda h: h and h.startswith("https://"))
            if not a:
                continue

            title_el = (
                block.select_one("h2.wgl-title")
                or block.select_one("h2")
                or block.select_one("h3")
            )
            title = (
                title_el.get_text(strip=True) if title_el else a.get_text(strip=True)
            )
            url = a.get("href", "")
            if not url.startswith("http"):
                continue

            snippet = ""
            desc = block.select_one("p.description") or block.select_one("p")
            if desc:
                snippet = desc.get_text(strip=True)

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
