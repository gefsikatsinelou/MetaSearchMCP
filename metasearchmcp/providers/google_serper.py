"""Google search via serper.dev API."""

from __future__ import annotations

from typing import ClassVar

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_MAX_API_RESULTS = 20


_SERPER_API_URL = "https://google.serper.dev/search"


class GoogleSerperProvider(BaseProvider):
    """Google search via serper.dev API."""

    name = "google_serper"
    description = "Google web search proxied through the Serper API."
    tags: ClassVar[list[str]] = ["google", "web"]

    def __init__(self) -> None:
        """Initialize the Google Serper provider with an API key."""
        super().__init__()
        self._api_key = get_settings().serper_api_key

    def is_available(self) -> bool:
        """Return whether the provider has a configured API key."""
        return bool(self._api_key)

    @staticmethod
    def country_code(country: str) -> str:
        """Normalize a country string to lowercase two-letter code for Serper."""
        return BaseProvider.country_code(country).lower()

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Google via Serper for *query* and return web results."""
        max_results = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        language_code = self._language_code(params.language)
        country_code = self.country_code(params.country)
        payload = {
            "q": query,
            "num": max_results,
            "hl": language_code,
            "gl": country_code,
        }
        headers = {
            "X-API-KEY": self._api_key,
            "Content-Type": "application/json",
        }

        async with self._client() as client:
            resp = await client.post(_SERPER_API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, max_results)

    def _parse(self, data: dict, max_results: int | None = None) -> ProviderResult:
        """Parse the API response into structured search results."""
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
        for item in data.get("relatedSearches", []):
            query = item.get("query", "").strip()
            if not query or query in seen_related:
                continue
            seen_related.add(query)
            related.append(query)

        answer_box: dict | None = None
        if "answerBox" in data:
            answer_box = data["answerBox"]
        elif "knowledgeGraph" in data:
            answer_box = data["knowledgeGraph"]

        return ProviderResult(
            results=results,
            related_searches=related,
            answer_box=answer_box,
        )
