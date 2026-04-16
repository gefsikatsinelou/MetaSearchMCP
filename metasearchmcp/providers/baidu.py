from __future__ import annotations

import json
from html import unescape

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider

_SEARCH_URL = "https://www.baidu.com/s"


class BaiduProvider(BaseProvider):
    """Baidu web search via the JSON result endpoint.

    Suitable for Chinese-language and China-region queries.
    Baidu has aggressive anti-bot detection; results in automated contexts
    may be limited or blocked. Best-effort.
    """

    name = "baidu"
    tags = ["web"]

    def is_available(self) -> bool:
        return get_settings().allow_unstable_providers

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        qp = {
            "wd": query,
            "rn": min(params.num_results, self._max_results, 10),
            "pn": 0,
            "tn": "json",
        }

        async with self._scraper_client() as client:
            resp = await client.get(_SEARCH_URL, params=qp)
            resp.raise_for_status()
            payload = resp.text.lstrip("\ufeff\r\n\t ")

        if not payload.startswith("{"):
            raise RuntimeError(
                "Baidu did not return JSON search results for this request"
            )

        data = json.loads(payload)

        return self._parse(data)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []
        entries = data.get("feed", {}).get("entry", [])

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
                )
            )
            if i >= self._max_results:
                break

        return ProviderResult(results=results)
