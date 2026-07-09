"""Bing web search via the public RSS response format."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_SEARCH_URL = "https://www.bing.com/search"


class BingProvider(BaseProvider):
    """Bing web search via the public RSS response format."""

    name = "bing"
    description = "Web search via Microsoft Bing."
    tags: ClassVar[list[str]] = ["web"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Bing for *query* via the public RSS endpoint."""
        language_code = self._language_code(params.language)
        country_code = self.country_code(params.country)
        qp = {
            "q": query,
            "format": "rss",
            "setlang": f"{language_code}-{country_code}",
            "mkt": f"{language_code}-{country_code}",
        }
        qp["adlt"] = "strict" if params.safe_search else "off"

        async with self._client() as client:
            resp = await client.get(_SEARCH_URL, params=qp)
            resp.raise_for_status()

        max_results = min(params.num_results, self._max_results)
        return self._parse(resp.text, max_results)

    def _parse(self, xml_text: str, max_results: int | None = None) -> ProviderResult:
        """Parse the XML response into structured search results."""
        results: list[SearchResult] = []
        root = ET.fromstring(xml_text)
        limit = max_results or self._max_results

        for i, item in enumerate(root.findall(".//item"), start=1):
            title = (item.findtext("title") or "").strip()
            url = (item.findtext("link") or "").strip()
            snippet = (item.findtext("description") or "").strip()
            if not url or not title:
                continue

            published_date = None
            raw_pub_date = (item.findtext("pubDate") or "").strip()
            if raw_pub_date:
                try:
                    published_date = (
                        parsedate_to_datetime(raw_pub_date).date().isoformat()
                    )
                except (TypeError, ValueError, IndexError):
                    published_date = None

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    rank=i,
                    provider=self.name,
                    published_date=published_date,
                ),
            )
            if i >= limit:
                break

        return ProviderResult(results=results)
