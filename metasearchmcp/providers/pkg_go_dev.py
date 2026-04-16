from __future__ import annotations

from bs4 import BeautifulSoup

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider

_BASE_URL = "https://pkg.go.dev"


class PkgGoDevProvider(BaseProvider):
    """pkg.go.dev — Go package/module search via HTML scraping.

    No authentication required.
    """

    name = "pkg_go_dev"
    tags = ["web", "code", "developer", "packages"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        async with self._scraper_client() as client:
            resp = await client.get(
                f"{_BASE_URL}/search",
                params={"q": query, "m": "package"},
            )
            resp.raise_for_status()
            html = resp.text

        return self._parse(html)

    def _parse(self, html: str) -> ProviderResult:
        soup = BeautifulSoup(html, "lxml")
        results: list[SearchResult] = []

        snippets = soup.select("div.SearchSnippet")
        for i, snip in enumerate(snippets, start=1):
            link_el = snip.select_one("div.SearchSnippet-headerContainer h2 a")
            if not link_el:
                continue

            href = link_el.get("href", "")
            title = link_el.get_text(strip=True)
            url = f"{_BASE_URL}{href}" if href.startswith("/") else href

            desc_el = snip.select_one("p.SearchSnippet-synopsis")
            content = desc_el.get_text(strip=True) if desc_el else ""

            version_el = snip.select_one("div.SearchSnippet-infoLabel span strong")
            version = version_el.get_text(strip=True) if version_el else ""

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=content,
                    source="pkg.go.dev",
                    rank=i,
                    provider=self.name,
                    extra={"version": version},
                )
            )

        return ProviderResult(results=results)
