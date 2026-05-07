"""Qwant search via their internal JSON API."""

from __future__ import annotations

from bs4 import BeautifulSoup

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

# Qwant's internal search API (used by their web frontend)
_API_URL = "https://api.qwant.com/v3/search/web"
_LITE_URL = "https://lite.qwant.com/"


class QwantProvider(BaseProvider):
    """Qwant search via their internal JSON API.

    The internal API endpoint (v3) currently returns 403 for non-browser
    requests. This provider is best-effort and may not work without a valid
    browser session or from residential IPs.
    """

    name = "qwant"
    description = "Privacy-focused European web search via Qwant."
    tags = ["web", "privacy"]

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
        language_code = self._language_code(params.language)
        country_code = self._country_code(params.country)
        locale = f"{language_code}_{country_code}"
        qp = {
            "q": query,
            "count": min(params.num_results, self._max_results, 10),
            "locale": locale,
            "offset": 0,
            "device": "desktop",
        }
        # Qwant requires an Origin / Referer header to accept requests
        extra_headers = {
            "Origin": "https://www.qwant.com",
            "Referer": "https://www.qwant.com/",
        }

        async with self._scraper_client() as client:
            resp = await client.get(_API_URL, params=qp, headers=extra_headers)
            if resp.status_code != 403:
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") == "success":
                    return self._parse(data)

            lite = await client.get(
                _LITE_URL,
                params={
                    "q": query,
                    "locale": locale.lower(),
                    "l": language_code,
                    "s": 1 if params.safe_search else 0,
                    "p": 1,
                },
                headers=extra_headers,
            )
            lite.raise_for_status()

        if "Service unavailable" in lite.text or "Unavailable" in lite.text[:500]:
            raise RuntimeError("Qwant Lite is currently unavailable from this network")

        return self._parse_lite(lite.text)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []

        items = (
            data.get("data", {}).get("result", {}).get("items", {}).get("mainline", [])
        )

        rank = 0
        for section in items:
            if section.get("type") != "web":
                continue
            for item in section.get("items", []):
                rank += 1
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        snippet=item.get("desc", ""),
                        rank=rank,
                        provider=self.name,
                    ),
                )
                if rank >= self._max_results:
                    return ProviderResult(results=results)

        return ProviderResult(results=results)

    def _parse_lite(self, html: str) -> ProviderResult:
        soup = BeautifulSoup(html, "lxml")
        results: list[SearchResult] = []

        for i, article in enumerate(soup.select("section article"), start=1):
            if article.select_one("span.tooltip"):
                continue

            title_node = article.select_one("h2 a")
            url_node = article.select_one("span.url.partner")
            snippet_node = article.select_one("p")
            if not title_node or not url_node:
                continue

            url = url_node.get_text(" ", strip=True)
            if not url.startswith("http"):
                url = f"https://{url.lstrip('/')}"

            results.append(
                SearchResult(
                    title=title_node.get_text(" ", strip=True),
                    url=url,
                    snippet=snippet_node.get_text(" ", strip=True)
                    if snippet_node
                    else "",
                    rank=i,
                    provider=self.name,
                ),
            )
            if i >= self._max_results:
                break

        return ProviderResult(results=results)
