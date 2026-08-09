"""Seznam.cz web search via HTML scraping.

Seznam is the dominant search engine in the Czech Republic and indexes the
Czech web (plus international results) with its own crawler. The public
results page requires no API key or authentication:

``GET https://search.seznam.cz/?q=QUERY``

Organic results are rendered server-side as anchors carrying the stable
``data-e-a="heading"`` attribute, so the parser relies on that attribute
rather than on obfuscated CSS class names (which rotate frequently).

Note: HTML structure may change without notice; parser is best-effort.
"""

from __future__ import annotations

from typing import ClassVar

from bs4 import BeautifulSoup

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_SEARCH_URL = "https://search.seznam.cz/"
# Label used by Seznam for sponsored blocks; results inside such blocks are
# still useful but flagged in ``extra`` so consumers can filter them out.
_SPONSORED_LABEL = "Sponzorované"


class SeznamProvider(BaseProvider):
    """Czech web search via Seznam.cz HTML scraping.

    No authentication required. Best-effort parser: result anchors are found
    through the stable ``data-e-a="heading"`` attribute and their enclosing
    block is walked to recover a snippet. Sponsored results are flagged via
    ``extra["sponsored"]``.
    """

    name = "seznam"
    description = "Czech web search via Seznam.cz own crawler index, no key required."
    tags: ClassVar[list[str]] = ["web"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Seznam.cz for *query* and return web results."""
        max_results = min(params.num_results, self._max_results)
        qp = {"q": query}

        async with self._scraper_client() as client:
            resp = await client.get(_SEARCH_URL, params=qp)
            resp.raise_for_status()

        return self._parse(resp.text, max_results=max_results)

    def _parse(self, html: str, max_results: int | None = None) -> ProviderResult:
        """Parse the HTML response into structured search results."""
        soup = BeautifulSoup(html, "lxml")
        results: list[SearchResult] = []
        limit = max_results or self._max_results
        seen_urls: set[str] = set()

        # Organic results are anchors with a stable data-e-a="heading" attr.
        for heading in soup.select('a[data-e-a="heading"]'):
            url = heading.get("href", "")
            title = heading.get_text(" ", strip=True)
            if not url.startswith("http") or not title:
                continue
            if url in seen_urls:
                continue

            block = self._find_result_block(heading)
            snippet = self._extract_snippet(block, title=title, url=url)
            sponsored = self._is_sponsored(heading)

            seen_urls.add(url)
            extra = {"sponsored": sponsored} if sponsored else {}
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    rank=len(results) + 1,
                    provider=self.name,
                    extra=extra,
                ),
            )
            if len(results) >= limit:
                break

        return ProviderResult(results=results)

    @staticmethod
    def _find_result_block(heading) -> object | None:
        """Walk up from *heading* to the enclosing div holding exactly one result.

        Seznam wraps each result in a ``div`` that contains exactly one
        ``data-e-a="heading"`` anchor; the nearest such ancestor is the
        result block used for snippet extraction.
        """
        node = heading
        for _ in range(8):
            node = node.parent
            if node is None:
                return None
            if node.name == "div" and len(node.select('a[data-e-a="heading"]')) == 1:
                return node
        return None

    @staticmethod
    def _is_sponsored(heading) -> bool:
        """Return True when *heading* sits inside a sponsored results block.

        Seznam wraps sponsored results under a section labelled
        ``Sponzorované výsledky``; the label lives in the container that
        directly wraps the sponsored block (about two levels above the
        individual result). Deeper ancestors wrap the whole result column,
        so only a short ancestor walk is performed.
        """
        node = heading
        for _ in range(3):
            node = node.parent
            if node is None:
                return False
            if _SPONSORED_LABEL in node.get_text(" ", strip=True):
                return True
        return False

    @staticmethod
    def _extract_snippet(block, title: str, url: str) -> str:
        """Return the best snippet text found inside *block*.

        Candidate text nodes are the ``div`` elements of the block; the
        title, the URL, redirect hints, and empty fragments are filtered
        out, and the longest remaining text wins.
        """
        if block is None:
            return ""
        candidates: list[str] = []
        for el in block.select("div"):
            text = el.get_text(" ", strip=True)
            if not text:
                continue
            if text == title or "Přejít na" in text or text.startswith("/"):
                continue
            if url and url in text:
                continue
            candidates.append(text)
        return max(candidates, key=len) if candidates else ""
