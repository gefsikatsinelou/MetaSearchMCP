"""Google search via serpbase.dev API."""

from __future__ import annotations

from typing import ClassVar

from metasearchmcp.config import SERPBASE_API_URL, get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_MAX_API_RESULTS = 20
_SERPBASE_STATUS_OK = 0


class GoogleSerpbaseProvider(BaseProvider):
    """Google search via serpbase.dev API."""

    name = "google_serpbase"
    description = "Google web search proxied through the SerpBase API."
    tags: ClassVar[list[str]] = ["google", "web"]

    _API_URL = SERPBASE_API_URL

    def __init__(self) -> None:
        """Initialize Serpbase provider with API key from settings."""
        super().__init__()
        self._api_key = get_settings().serpbase_api_key

    def is_available(self) -> bool:
        """Return True when a Serpbase API key is configured."""
        return bool(self._api_key)

    @staticmethod
    def country_code(country: str) -> str:
        """Normalize a country string to lowercase two-letter code for Serpbase."""
        return BaseProvider.country_code(country).lower()

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Google for *query* via the Serpbase API."""
        max_results = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        language_code = self._language_code(params.language)
        country_code = self.country_code(params.country)
        payload = {
            "q": query,
            "hl": language_code,
            "gl": country_code,
            "page": 1,
        }
        headers = {"X-API-Key": self._api_key}

        async with self._client() as client:
            resp = await client.post(self._API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != _SERPBASE_STATUS_OK:
                raise RuntimeError(
                    data.get("error") or f"serpbase error status={data.get('status')}",
                )

        return self._parse(data, max_results)

    def _parse(self, data: dict, max_results: int | None = None) -> ProviderResult:
        results: list[SearchResult] = []
        limit = max_results or self._max_results

        for i, item in enumerate(data.get("organic", []), start=1):
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("link", ""),
                    snippet=item.get("snippet", ""),
                    rank=i,
                    provider=self.name,
                    published_date=item.get("date"),
                ),
            )
            if i >= limit:
                break

        related: list[str] = []
        seen_related: set[str] = set()
        for item in data.get("related_searches", []):
            if item is None:
                continue
            query_text = str(item).strip()
            if not query_text or query_text in seen_related:
                continue
            seen_related.add(query_text)
            related.append(query_text)
        answer_box = (
            data.get("ai_overview")
            or data.get("knowledge_graph")
            or data.get("weather")
            or data.get("finance")
            or data.get("flight")
            or None
        )

        return ProviderResult(
            results=results,
            related_searches=related,
            answer_box=answer_box,
        )
