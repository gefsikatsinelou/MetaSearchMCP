"""Marginalia search — independent search engine for the non-commercial web.

Marginalia.nu indexes the "old web": personal blogs, small wikis, niche
communities, and other non-commercial sites that big search engines bury.
Its public API requires no API key and returns clean JSON:

``GET https://api.marginalia.nu/public/search/QUERY?count=N``

Each result carries the URL, title, description, a quality score, and the
number of pages indexed from the same domain.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://api.marginalia.nu/public/search/"


class MarginaliaProvider(BaseProvider):
    """Search the non-commercial web index of Marginalia.

    Uses the keyless public JSON API. Results are biased toward small,
    independent, text-first websites rather than commercial domains.
    """

    name = "marginalia"
    description = (
        "Independent search engine for the non-commercial web "
        "(personal blogs, small wikis, niche communities), no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "general"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Marginalia for *query* and return web results."""
        limit = min(params.num_results, self._max_results)
        async with self._client() as client:
            resp = await client.get(_API_URL + query, params={"count": str(limit)})
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the API response into structured search results."""
        results: list[SearchResult] = []
        for i, item in enumerate(data.get("results", []), start=1):
            if not isinstance(item, dict):
                continue
            url = item.get("url", "")
            title = item.get("title", "")
            if not url or not title:
                continue

            quality = item.get("quality")
            domain_pages = item.get("resultsFromDomain")
            extra: dict[str, Any] = {}
            if isinstance(quality, (int, float)):
                extra["quality"] = round(float(quality), 2)
            if isinstance(domain_pages, int):
                extra["pages_from_domain"] = domain_pages

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=item.get("description", ""),
                    source="marginalia.nu",
                    rank=i,
                    provider=self.name,
                    extra=extra,
                ),
            )

        return ProviderResult(results=results)
