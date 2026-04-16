from __future__ import annotations

from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider

_BASE_URL = "https://lib.rs"


class LibRsProvider(BaseProvider):
    """lib.rs — alternative Rust crate search via HTML scraping.

    Complements crates.io with different ranking and discoverability.
    No authentication required.
    """

    name = "lib_rs"
    tags = ["web", "code", "developer", "packages"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        async with self._scraper_client() as client:
            resp = await client.get(
                f"{_BASE_URL}/search",
                params={"q": query},
            )
            resp.raise_for_status()
            html = resp.text

        return self._parse(html)

    def _parse(self, html: str) -> ProviderResult:
        soup = BeautifulSoup(html, "lxml")
        results: list[SearchResult] = []

        # lib.rs renders results as <ol><li><a ...> per result
        for i, anchor in enumerate(soup.select("main div ol li a"), start=1):
            href = anchor.get("href", "")
            url = f"{_BASE_URL}{href}" if href.startswith("/") else href

            title_el = anchor.select_one("div.h h4")
            title = title_el.get_text(strip=True) if title_el else href.lstrip("/")

            desc_el = anchor.select_one("div.h p")
            content = desc_el.get_text(strip=True) if desc_el else ""

            version_el = anchor.select_one("div.meta span.version")
            version = version_el.get_text(strip=True) if version_el else ""

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=content,
                    source="lib.rs",
                    rank=i,
                    provider=self.name,
                    extra={"version": version},
                )
            )

        return ProviderResult(results=results)
