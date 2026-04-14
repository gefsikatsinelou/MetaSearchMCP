from __future__ import annotations

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider


class GoogleSerpbaseProvider(BaseProvider):
    """Google search via serpbase.dev API."""

    name = "google_serpbase"
    tags = ["google", "web"]

    _API_URL = "https://api.serpbase.dev/google/search"

    def __init__(self) -> None:
        super().__init__()
        self._api_key = get_settings().serpbase_api_key

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        payload = {
            "q": query,
            "hl": params.language,
            "gl": params.country,
            "page": 1,
        }
        headers = {"X-API-Key": self._api_key}

        async with self._client() as client:
            resp = await client.post(self._API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != 0:
                raise RuntimeError(
                    data.get("error") or f"serpbase error status={data.get('status')}"
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
                )
            )

        related = [r for r in data.get("related_searches", []) if r]
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
