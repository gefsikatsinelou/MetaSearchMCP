from __future__ import annotations

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider


class GoogleSerperProvider(BaseProvider):
    """Google search via serper.dev API."""

    name = "google_serper"
    tags = ["google", "web"]

    _API_URL = "https://google.serper.dev/search"

    def __init__(self) -> None:
        super().__init__()
        self._api_key = get_settings().serper_api_key

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        payload = {
            "q": query,
            "num": min(params.num_results, self._max_results),
            "hl": params.language,
            "gl": params.country,
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
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
                rank=i,
                provider=self.name,
                published_date=item.get("date"),
            ))

        related = [r.get("query", "") for r in data.get("relatedSearches", [])]

        answer_box: dict | None = None
        if "answerBox" in data:
            answer_box = data["answerBox"]
        elif "knowledgeGraph" in data:
            answer_box = data["knowledgeGraph"]

        return ProviderResult(
            results=results,
            related_searches=[r for r in related if r],
            answer_box=answer_box,
        )
