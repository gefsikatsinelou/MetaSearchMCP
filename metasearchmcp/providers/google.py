"""Direct Google web search via HTML scraping."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup, Tag

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
    "div[data-sncf='1']",
)
_ANSWER_BOX_SELECTORS = (
    "div.IZ6rdc",
    "div.kno-rdesc",
    "div.hgKElc",
    "div[data-attrid='wa:/description']",
)
_WHITESPACE_RE = re.compile(r"\s+")
_GOOGLE_BASE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/39.0.2374.1981 Mobile Safari/537.36 NSTNWV"
)


class GoogleProvider(BaseProvider):
    """Direct Google web search via HTML scraping."""

    name = "google"
    description = "Direct Google web search via HTML scraping."
    tags = ["google", "web"]

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
        region = normalized.rsplit("-", 1)[-1].lower()
        return region or "us"

    @staticmethod
    def _build_user_agent(language_code: str, country_code: str) -> str:
        locale_suffix = f"{language_code}-{country_code.upper()}"
        chrome_patch = 1980 + ((sum(ord(char) for char in locale_suffix) % 17) + 1)
        return (
            "Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/39.0.2374.{chrome_patch} Mobile Safari/537.36 "
            f"NSTNWV {locale_suffix}"
        )

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        language_code = self._language_code(params.language)
        country_code = self._country_code(params.country)
        request_params = {
            "q": query,
            "hl": f"{language_code}-{country_code.upper()}",
            "lr": f"lang_{language_code}",
            "gl": country_code,
            "ie": "utf8",
            "oe": "utf8",
            "filter": "0",
            "start": 0,
            "safe": _SAFE_SEARCH[params.safe_search],
        }
        cookies = {"CONSENT": "YES+"}
        headers = {
            "Accept": "*/*",
            "User-Agent": self._build_user_agent(language_code, country_code),
        }

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
                'a[href^="http"]',
            )
            title_node = block.select_one("h3") or block.select_one(
                'div[role="heading"]',
            )
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
                ),
            )
            if len(results) >= self._max_results:
                break

        related_searches = self._extract_related_searches(soup)
        answer_box = self._extract_answer_box(soup)

        return ProviderResult(
            results=results,
            related_searches=related_searches,
            answer_box=answer_box,
        )

    @staticmethod
    def _extract_result_url(href: str) -> str:
        if not href:
            return ""
        if href.startswith("/url?"):
            query = parse_qs(urlparse(href).query)
            target = query.get("q", [""])[0]
            target = unquote(target)
            parsed = urlparse(target)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                return target
            return ""
        if href.startswith("http"):
            parsed = urlparse(href)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                return href
        return ""

    @staticmethod
    def _extract_snippet(block: Tag) -> str:
        for selector in _SNIPPET_SELECTORS:
            snippet_node = block.select_one(selector)
            if snippet_node:
                return GoogleProvider._normalize_text(
                    snippet_node.get_text(" ", strip=True),
                )
        return ""

    @staticmethod
    def _extract_related_searches(soup: BeautifulSoup) -> list[str]:
        related_searches: list[str] = []
        selectors = (
            "div.gGQDvd a",
            "div.s75CSd a",
            "div.BNeawe.s3v9rd.AP7Wnd a",
        )
        for selector in selectors:
            for suggestion in soup.select(selector):
                href = suggestion.get("href", "")
                if "q=" not in href:
                    continue
                text = GoogleProvider._normalize_text(
                    suggestion.get_text(" ", strip=True),
                )
                if text and text not in related_searches:
                    related_searches.append(text)
        return related_searches

    @staticmethod
    def _extract_answer_box(soup: BeautifulSoup) -> dict | None:
        for selector in _ANSWER_BOX_SELECTORS:
            node = soup.select_one(selector)
            if node:
                text = GoogleProvider._normalize_text(node.get_text(" ", strip=True))
                if text:
                    return {"text": text}
        return None

    @staticmethod
    def _normalize_text(text: str) -> str:
        return _WHITESPACE_RE.sub(" ", text).strip()
