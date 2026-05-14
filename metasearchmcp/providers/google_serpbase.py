"""Google search via serpbase.dev API."""

from __future__ import annotations

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider


class GoogleSerpbaseProvider(BaseProvider):
    """Google search via serpbase.dev API."""

    name = "google_serpbase"
    description = "Google web search proxied through the SerpBase API."
    tags = ["google", "web"]

    _API_URL = "https://api.serpbase.dev/google/search"

    def __init__(self) -> None:
        """Initialize Serpbase provider with API key from settings."""
        super().__init__()
        self._api_key = get_settings().serpbase_api_key

    def is_available(self) -> bool:
        """Return True when a Serpbase API key is configured."""
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
        """Search Google for *query* via the Serpbase API."""
        language_code = self._language_code(params.language)
        country_code = self._country_code(params.country)
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
            if data.get("status") != 0:
                raise RuntimeError(
                    data.get("error") or f"serpbase error status={data.get('status')}",
                )

        return self._parse(data, query)

    def _parse(self, data: dict, query: str) -> ProviderResult:
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
