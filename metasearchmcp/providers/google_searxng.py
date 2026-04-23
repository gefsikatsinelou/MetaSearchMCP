from __future__ import annotations

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider


class GoogleSearXNGProvider(BaseProvider):
    """Google search via a SearXNG instance configured to use the google engine."""

    name = "google_searxng"
    description = "Google web search routed through a SearXNG instance."
    tags = ["google", "web"]

    def __init__(self) -> None:
        super().__init__()
        self._base_url = get_settings().searxng_base_url.rstrip("/")

    def is_available(self) -> bool:
        return bool(self._base_url)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        request_params = {
            "q": query,
            "format": "json",
            "engines": "google",
            "language": params.language,
            "safesearch": 1 if params.safe_search else 0,
        }
        if params.country:
            request_params["locale"] = f"{params.language}-{params.country.upper()}"

        async with self._client() as client:
            resp = await client.get(f"{self._base_url}/search", params=request_params)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []

        for i, item in enumerate(data.get("results", []), start=1):
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", ""),
                    rank=i,
                    provider=self.name,
                )
            )

        related_searches = [s for s in data.get("suggestions", []) if s]
        answer_box = data.get("infoboxes") or None
        if isinstance(answer_box, list) and len(answer_box) == 1:
            answer_box = answer_box[0]

        return ProviderResult(
            results=results,
            related_searches=related_searches,
            answer_box=answer_box,
        )
