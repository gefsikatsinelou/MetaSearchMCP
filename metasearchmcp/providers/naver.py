"""Naver web search via HTML scraping.

Naver is the dominant search engine in South Korea and indexes the Korean
web with its own crawler. The public results page requires no API key or
authentication:

``GET https://search.naver.com/search.naver?query=QUERY``

Organic results are rendered server-side as ``<li class="bx">`` items whose
heading anchor carries the ``link_tit`` / ``tit`` classes. Advertisements
are flagged through ``data-ad`` attributes, dedicated ad markers, or the
``ad`` / ``bizsite`` class names on the item, so the parser skips them.

Note: HTML structure may change without notice; parser is best-effort.
"""

from __future__ import annotations

from typing import ClassVar

from bs4 import BeautifulSoup, Tag

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_SEARCH_URL = "https://search.naver.com/search.naver"
# Server-rendered organic results live inside <li class="bx"> blocks.
_RESULT_SELECTOR = "li.bx"
# Title anchors: desktop layout uses link_tit, compact views use tit.
_TITLE_SELECTORS = ("a.link_tit", "a.tit")
# Description containers, from most to least specific.
_SNIPPET_SELECTORS = (
    "div.api_txt_lines",
    "div.total_dsc",
    "div.total_dsc_wrap",
    "div.total_doc",
)
# Class fragments that mark an item as an advertisement (skipped).
_AD_MARKERS = ("ad", "bizsite", "brand", "sh_blog_top")
_MAX_SNIPPET_CHARS = 300


class NaverProvider(BaseProvider):
    """South Korean web search via Naver HTML scraping.

    Keyless and best-effort: result items are located through the stable
    ``li.bx`` block plus ``link_tit`` / ``tit`` heading anchors, and ads
    are dropped. Gated behind the unstable-providers flag because Naver
    applies anti-bot measures to datacenter traffic.
    """

    name = "naver"
    description = "South Korean web search via Naver, no key required."
    tags: ClassVar[list[str]] = ["web"]

    def is_available(self) -> bool:
        """Return whether Naver is enabled via unstable-provider flag."""
        return get_settings().allow_unstable_providers

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Naver for *query* and return web results."""
        max_results = min(params.num_results, self._max_results)

        async with self._scraper_client() as client:
            resp = await client.get(_SEARCH_URL, params={"query": query})
            resp.raise_for_status()

        return self._parse(resp.text, max_results=max_results)

    def _parse(self, html: str, max_results: int | None = None) -> ProviderResult:
        """Parse the HTML response into structured search results."""
        soup = BeautifulSoup(html, "lxml")
        results: list[SearchResult] = []
        limit = max_results or self._max_results
        seen_urls: set[str] = set()

        for item in soup.select(_RESULT_SELECTOR):
            if len(results) >= limit:
                break
            if self._is_ad(item):
                continue

            anchor = self._find_title_anchor(item)
            if anchor is None:
                continue
            title = anchor.get_text(" ", strip=True)
            url = anchor.get("href", "")
            if not title or not url.startswith("http"):
                continue
            if url in seen_urls:
                continue

            snippet = self._extract_snippet(item)

            seen_urls.add(url)
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    rank=len(results) + 1,
                    provider=self.name,
                ),
            )

        return ProviderResult(results=results)

    @staticmethod
    def _find_title_anchor(item: Tag) -> Tag | None:
        """Return the heading anchor of *item* (or ``None`` if not found)."""
        for selector in _TITLE_SELECTORS:
            anchor = item.select_one(selector)
            if anchor is not None:
                return anchor
        return None

    @staticmethod
    def _is_ad(item: Tag) -> bool:
        """Return True when *item* looks like an advertisement block.

        Naver marks ad items with a ``data-ad`` attribute, an ad-related
        ``id``/class, or an ``ad``-class wrapper inside the block.
        """
        if item.get("data-ad"):
            return True
        classes = " ".join(item.get("class", []))
        item_id = item.get("id", "") or ""
        if any(marker in classes or marker in item_id for marker in _AD_MARKERS):
            return True
        return item.select_one(".ad, .bizsite, .brand_link") is not None

    @staticmethod
    def _extract_snippet(item: Tag) -> str:
        """Return the best snippet text found inside *item*.

        Naver descriptions live in a handful of containers; the first one
        carrying text wins, truncated for consistency.
        """
        for selector in _SNIPPET_SELECTORS:
            block = item.select_one(selector)
            if block is None:
                continue
            text = block.get_text(" ", strip=True)
            if text:
                return text[:_MAX_SNIPPET_CHARS]
        return ""
