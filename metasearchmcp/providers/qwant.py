from __future__ import annotations

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider

# Qwant's internal search API (used by their web frontend)
_API_URL = "https://api.qwant.com/v3/search/web"


class QwantProvider(BaseProvider):
    """Qwant search via their internal JSON API.

    The internal API endpoint (v3) currently returns 403 for non-browser
    requests. This provider is best-effort and may not work without a valid
    browser session or from residential IPs.
    """

    name = "qwant"
    tags = ["web", "privacy"]

    def is_available(self) -> bool:
        return get_settings().allow_unstable_providers

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        qp = {
            "q": query,
            "count": min(params.num_results, self._max_results, 10),
            "locale": f"{params.language}_{params.country.upper()}",
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
            if resp.status_code == 403:
                raise RuntimeError(
                    "Qwant rejected the request with 403; browser session likely required"
                )
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") != "success":
            error_code = data.get("data", {}).get("error_code")
            raise RuntimeError(
                f"Qwant search failed with status={data.get('status')} error_code={error_code}"
            )

        return self._parse(data)

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
                    )
                )
                if rank >= self._max_results:
                    return ProviderResult(results=results)

        return ProviderResult(results=results)
