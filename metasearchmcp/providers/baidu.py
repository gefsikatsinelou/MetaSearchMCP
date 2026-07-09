"""Baidu web search via the JSON result endpoint."""

from __future__ import annotations

import json
from html import unescape
from typing import ClassVar

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_SEARCH_URL = "https://www.baidu.com/s"
_MAX_API_RESULTS = 10
_ERR_BAIDU_NOT_JSON = "Baidu did not return JSON search results for this request"


class BaiduProvider(BaseProvider):
    """Baidu web search via the JSON result endpoint.

    Suitable for Chinese-language and China-region queries.
    Baidu has aggressive anti-bot detection; results in automated contexts
    may be limited or blocked. Best-effort.
    """

    name = "baidu"
    description = "Web search via Baidu."
    tags: ClassVar[list[str]] = ["web"]

    def is_available(self) -> bool:
        """Return whether Baidu is enabled via unstable-provider flag."""
        return get_settings().allow_unstable_providers

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Baidu for *query* via the JSON endpoint."""
        max_results = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        qp = {
            "wd": query,
            "rn": max_results,
            "pn": 0,
            "tn": "json",
        }

        async with self._scraper_client() as client:
            resp = await client.get(_SEARCH_URL, params=qp)
            resp.raise_for_status()
            payload = resp.text.lstrip("\ufeff\r\n\t ")

        if not payload.startswith("{"):
            raise RuntimeError(_ERR_BAIDU_NOT_JSON)

        data = json.loads(payload)

        return self._parse(data, max_results=max_results)

    def _parse(self, data: dict, max_results: int | None = None) -> ProviderResult:
        """Parse the API response into structured search results."""
        results: list[SearchResult] = []
        entries = data.get("feed", {}).get("entry", [])
        limit = max_results or self._max_results

        for i, entry in enumerate(entries, start=1):
            title = unescape(entry.get("title", "") or "")
            url = entry.get("url", "") or ""
            if not title or not url:
                continue
            snippet = unescape(entry.get("abs", "") or "")

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    rank=i,
                    provider=self.name,
                ),
            )
            if i >= limit:
                break

        return ProviderResult(results=results)
