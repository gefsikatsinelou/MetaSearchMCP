from __future__ import annotations

from urllib.parse import unquote

from bs4 import BeautifulSoup

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider

_REGION_TO_DOMAIN = {
    "CA": "ca.search.yahoo.com",
    "DE": "de.search.yahoo.com",
    "FR": "fr.search.yahoo.com",
    "GB": "uk.search.yahoo.com",
    "UK": "uk.search.yahoo.com",
    "IN": "in.search.yahoo.com",
    "SG": "sg.search.yahoo.com",
}

_LANGUAGE_MAP = {
    "ar": "ar",
    "de": "de",
    "en": "en",
    "es": "es",
    "fr": "fr",
    "it": "it",
    "ja": "ja",
    "ko": "ko",
    "nl": "nl",
    "pt": "pt",
    "ru": "ru",
    "zh": "zh_chs",
    "zh-cn": "zh_chs",
    "zh-hans": "zh_chs",
    "zh-tw": "zh_cht",
    "zh-hant": "zh_cht",
}


class YahooProvider(BaseProvider):
    """Yahoo web search via HTML scraping with Yahoo's expected cookie flow."""

    name = "yahoo"
    description = "Web search via Yahoo Search."
    tags = ["web"]

    def is_available(self) -> bool:
        return get_settings().allow_unstable_providers

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
        domain = _REGION_TO_DOMAIN.get(
            self._country_code(params.country), "search.yahoo.com"
        )
        language = _LANGUAGE_MAP.get(self._language_code(params.language), "en")
        qp = {
            "p": query,
            "iscqry": "",
            "n": min(params.num_results, self._max_results, 10),
            "ei": "UTF-8",
        }
        cookie = self._build_sb_cookie(
            language=language, safe_search=params.safe_search
        )

        async with self._scraper_client() as client:
            resp = await client.get(
                f"https://{domain}/search", params=qp, cookies={"sB": cookie}
            )
            if resp.status_code >= 500:
                raise RuntimeError(
                    f"Yahoo returned HTTP {resp.status_code}; request likely blocked upstream"
                )
            resp.raise_for_status()

        return self._parse(resp.text, domain=domain)

    @staticmethod
    def _build_sb_cookie(*, language: str, safe_search: bool) -> str:
        vm = "i" if safe_search else "p"
        return "&".join(
            [
                "v=1",
                f"vm={vm}",
                "fl=1",
                f"vl=lang_{language}",
                "pn=10",
                "rw=new",
                "userset=1",
            ]
        )

    @staticmethod
    def _unwrap_url(url: str) -> str:
        if "/RU=" not in url:
            return url

        start = url.find("http", url.find("/RU=") + 1)
        if start < 0:
            return url

        end = len(url)
        for suffix in ("/RK=", "/RS="):
            idx = url.find(suffix, start)
            if idx >= 0:
                end = min(end, idx)
        return unquote(url[start:end])

    def _parse(self, html: str, *, domain: str = "search.yahoo.com") -> ProviderResult:
        soup = BeautifulSoup(html, "lxml")
        results: list[SearchResult] = []
        suggestions: list[str] = []

        containers = (
            soup.select("div.algo-sr")
            or soup.select("div#web li")
            or soup.select("div.algo")
        )

        for i, block in enumerate(containers, start=1):
            url_node = (
                block.select_one("div.compTitle a")
                or block.select_one("h3 a")
                or block.select_one("h2 a")
            )
            if not url_node:
                continue
            title_node = None
            if domain == "search.yahoo.com":
                title_node = block.select_one(
                    "div.compTitle a h3 span"
                ) or block.select_one("div.compTitle a")
            else:
                title_node = block.select_one("div.compTitle h3 a") or block.select_one(
                    "h3 a"
                )

            title = (title_node or url_node).get_text(" ", strip=True)
            url = self._unwrap_url(url_node.get("href", ""))

            snippet = ""
            for sel in (
                "div.compText",
                "div.compText p",
                "p.fz-ms",
                "div.s p",
                ".compText span",
            ):
                el = block.select_one(sel)
                if el:
                    snippet = " ".join(el.get_text(" ", strip=True).split())
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

        for node in soup.select("div.AlsoTry a, div.AlsoTry table a"):
            text = node.get_text(" ", strip=True)
            if text and text not in suggestions:
                suggestions.append(text)

        return ProviderResult(results=results, suggestions=suggestions)
