"""DuckDuckGo search via HTML scraping of the lite endpoint."""

from __future__ import annotations

from typing import ClassVar
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

# DuckDuckGo's HTML endpoint still exposes server-rendered results.
_HTML_URL = "https://html.duckduckgo.com/html/"


class DuckDuckGoProvider(BaseProvider):
    """DuckDuckGo search via HTML scraping of the lite endpoint."""

    name = "duckduckgo"
    description = "Privacy-focused web search via DuckDuckGo."
    tags: ClassVar[list[str]] = ["web", "privacy"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search DuckDuckGo for *query* via the HTML endpoint."""
        language_code = self._language_code(params.language)
        country_code = self._country_code(params.country)
        qp = {
            "q": query,
            "kl": f"{language_code}-{country_code}",
        }
        qp["kp"] = "1" if params.safe_search else "-2"

        async with self._scraper_client() as client:
            resp = await client.get(_HTML_URL, params=qp)
            resp.raise_for_status()

        max_results = min(params.num_results, self._max_results)
        return self._parse(resp.text, max_results)

    def _parse(self, html: str, max_results: int | None = None) -> ProviderResult:
        soup = BeautifulSoup(html, "lxml")
        results: list[SearchResult] = []
        limit = max_results or self._max_results

        for i, block in enumerate(soup.select("div.result"), start=1):
            a = block.select_one(".result__title a") or block.select_one("a.result__a")
            if not a:
                continue

            href = a.get("href", "")
            title = a.get_text(" ", strip=True)
            snippet_el = block.select_one(".result__snippet")
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""

            parsed = urlparse(href)
            if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith(
                "/l/",
            ):
                href = parse_qs(parsed.query).get("uddg", [href])[0]

            if not href or not title:
                continue

            results.append(
                SearchResult(
                    title=title,
                    url=href,
                    snippet=snippet,
                    rank=i,
                    provider=self.name,
                ),
            )

            if i >= limit:
                break

        return ProviderResult(results=results)
