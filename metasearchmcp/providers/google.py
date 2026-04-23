from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider

_SEARCH_URL = "https://www.google.com/search"
_SAFE_SEARCH = {False: "off", True: "active"}
_SNIPPET_SELECTORS = (
    "div.VwiC3b",
    "div.yXK7lf",
    "div.s3v9rd",
    "span.aCOpRe",
)


class GoogleProvider(BaseProvider):
    """Direct Google web search via HTML scraping."""

    name = "google"
    description = "Direct Google web search via HTML scraping."
    tags = ["google", "web"]

    def is_available(self) -> bool:
        return get_settings().allow_unstable_providers

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        request_params = {
            "q": query,
            "hl": f"{params.language}-{params.country.upper()}",
            "lr": f"lang_{params.language}",
            "gl": params.country.lower(),
            "ie": "utf8",
            "oe": "utf8",
            "filter": "0",
            "start": 0,
            "safe": _SAFE_SEARCH[params.safe_search],
        }
        cookies = {"CONSENT": "YES+"}
        headers = {"Accept": "*/*"}

        async with self._scraper_client() as client:
            resp = await client.get(
                _SEARCH_URL,
                params=request_params,
                cookies=cookies,
                headers=headers,
            )
            resp.raise_for_status()

        self._raise_on_blocked_response(resp.text, str(resp.url))
        return self._parse(resp.text)

    @staticmethod
    def _raise_on_blocked_response(html: str, url: str) -> None:
        lowered = html.lower()
        if "/sorry/" in url or "unusual traffic from your computer network" in lowered:
            raise RuntimeError("Google rejected the request as automated traffic")

    def _parse(self, html: str) -> ProviderResult:
        soup = BeautifulSoup(html, "lxml")
        results: list[SearchResult] = []
        seen_urls: set[str] = set()

        containers = soup.select("div.g, div.Gx5Zad, div.MjjYud")
        for block in containers:
            anchor = block.select_one('a[href^="/url?q="]') or block.select_one(
                'a[href^="http"]'
            )
            title_node = block.select_one("h3") or block.select_one('div[role="heading"]')
            if not anchor or not title_node:
                continue

            href = anchor.get("href", "")
            url = self._extract_result_url(href)
            title = title_node.get_text(" ", strip=True)
            if not url or not title or url in seen_urls:
                continue

            seen_urls.add(url)
            snippet = self._extract_snippet(block)
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

        related_searches = []
        for suggestion in soup.select('div.gGQDvd.iIWm4b a, a[href*="&q="]'):
            text = suggestion.get_text(" ", strip=True)
            if text and text not in related_searches:
                related_searches.append(text)

        return ProviderResult(results=results, related_searches=related_searches)

    @staticmethod
    def _extract_result_url(href: str) -> str:
        if not href:
            return ""
        if href.startswith("/url?"):
            query = parse_qs(urlparse(href).query)
            target = query.get("q", [""])[0]
            return unquote(target)
        if href.startswith("http"):
            return href
        return ""

    @staticmethod
    def _extract_snippet(block) -> str:
        for selector in _SNIPPET_SELECTORS:
            snippet_node = block.select_one(selector)
            if snippet_node:
                return snippet_node.get_text(" ", strip=True)
        return ""
