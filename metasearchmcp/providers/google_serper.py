"""Google search via serper.dev API."""

from __future__ import annotations

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider


class GoogleSerperProvider(BaseProvider):
    """Google search via serper.dev API."""

    name = "google_serper"
    description = "Google web search proxied through the Serper API."
    tags = ["google", "web"]

    _API_URL = "https://google.serper.dev/search"

    def __init__(self) -> None:
        """Initialize the Google Serper provider with an API key."""
        super().__init__()
        self._api_key = get_settings().serper_api_key

    def is_available(self) -> bool:
        """Return whether the provider has a configured API key."""
        return bool(self._api_key)

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

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Google via Serper for *query* and return web results."""
        language_code = self._language_code(params.language)
        country_code = self._country_code(params.country)
        payload = {
            "q": query,
            "num": min(params.num_results, self._max_results),
            "hl": language_code,
            "gl": country_code,
        }
        headers = {
            "X-API-KEY": self._api_key,
            "Content-Type": "application/json",
        }

        async with self._client() as client:
            resp = await client.post(self._API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []

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
