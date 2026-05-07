"""Yandex web search via HTML scraping."""

from __future__ import annotations

from bs4 import BeautifulSoup

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_SEARCH_URL = "https://yandex.com/search/site/"
_SUPPORTED_LANGS = {"ru", "en", "be", "fr", "de", "id", "kk", "tt", "tr", "uk"}


class YandexProvider(BaseProvider):
    """Yandex web search via HTML scraping.

    Yandex returns a mostly client-side-rendered response to non-browser
    requests; results are typically empty from datacenter IPs. May work on
    residential IPs or with a proxy that has established cookies.
    Note: HTML structure may change without notice; parser is best-effort.
    """

    name = "yandex"
    description = "Web search via Yandex."
    tags = ["web"]

    def is_available(self) -> bool:
        return get_settings().allow_unstable_providers

    @staticmethod
    def _language_code(language: str) -> str:
        normalized = (language or "en").strip().replace("_", "-")
        primary = normalized.split("-", 1)[0].lower()
        return primary or "en"

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        qp = {
            "tmpl_version": "releases",
            "text": query,
            "web": "1",
            "frame": "1",
            "searchid": "3131712",
        }
        lang = self._language_code(params.language)
        if lang in _SUPPORTED_LANGS:
            qp["lang"] = lang
        cookies = {
            "cookie": "yp=1716337604.sp.family%3A0#1685406411.szm.1:1920x1080:1920x999",
        }

        async with self._scraper_client() as client:
            resp = await client.get(_SEARCH_URL, params=qp, cookies=cookies)
            resp.raise_for_status()

        if resp.headers.get("x-yandex-captcha") == "captcha":
            raise RuntimeError("Yandex requested a captcha challenge for this network")

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
