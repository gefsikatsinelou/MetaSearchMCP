"""DuckDuckGo search via HTML scraping of the lite endpoint."""

from __future__ import annotations

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
    tags = ["web", "privacy"]

    @staticmethod
    def _language_code(language: str) -> str:
        normalized = (language or "en").strip().replace("_", "-")
        primary = normalized.split("-", 1)[0].lower()
        return primary or "en"

    @staticmethod
    def _country_code(country: str) -> str:
        normalized = (country or "us").strip().replace("_", "-")
        region = normalized.rsplit("-", 1)[-1].upper()
        return region or "US"

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

        return self._parse(resp.text)

    def _parse(self, html: str) -> ProviderResult:
        soup = BeautifulSoup(html, "lxml")
        results: list[SearchResult] = []

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

            if i >= self._max_results:
                break

        return ProviderResult(results=results)
