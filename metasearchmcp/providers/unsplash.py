"""Unsplash photo search via the official API.

``GET https://api.unsplash.com/search/photos`` returns curated stock
photos matching the query as JSON. An access key is required:

- Register a free developer account at https://unsplash.com/developers
- Set ``UNSPLASH_ACCESS_KEY`` in your environment / ``.env`` file

Each result carries the landing page, thumbnail and full-size image URLs,
photographer name, dimensions, dominant color, and creation date.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://api.unsplash.com/search/photos"
# The public API caps per_page at 30.
_MAX_PER_PAGE = 30


class UnsplashProvider(BaseProvider):
    """Search curated stock photos on Unsplash by keyword.

    Requires an Unsplash access key (``UNSPLASH_ACCESS_KEY``); without one
    the provider reports itself unavailable and is excluded from the registry.
    """

    name = "unsplash"
    description = (
        "Search high-quality curated stock photos on Unsplash by keyword "
        "(requires UNSPLASH_ACCESS_KEY)."
    )
    tags: ClassVar[list[str]] = ["image", "media"]

    def __init__(self) -> None:
        """Initialize provider and load the Unsplash access key."""
        super().__init__()
        self._api_key = get_settings().unsplash_access_key

    def is_available(self) -> bool:
        """Return True when an Unsplash access key is configured."""
        return bool(self._api_key)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Unsplash for photos matching *query*."""
        per_page = min(params.num_results, self._max_results, _MAX_PER_PAGE)
        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={
                    "query": query,
                    "per_page": per_page,
                    "client_id": self._api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, per_page)

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    def _parse(self, data: dict[str, Any], limit: int | None = None) -> ProviderResult:
        """Parse the search/photos response into structured search results."""
        results: list[SearchResult] = []
        max_results = limit or self._max_results

        for i, item in enumerate(data.get("results", []), start=1):
            if i > max_results:
                break
            links = item.get("links") or {}
            page_url = links.get("html") or ""
            if not page_url:
                continue

            urls = item.get("urls") or {}
            user = item.get("user") or {}
            author = self._clean(user.get("name"))
            alt = self._clean(item.get("alt_description"))
            description = self._clean(item.get("description"))
            photo_id = item.get("id") or ""
            title = alt or description or f"Unsplash photo ({photo_id})"

            width = item.get("width")
            height = item.get("height")

            snippet_parts: list[str] = []
            if description:
                snippet_parts.append(description)
            if author:
                snippet_parts.append(f"Photographer: {author}")
            if width and height:
                snippet_parts.append(f"{width}x{height}")

            results.append(
                SearchResult(
                    title=title,
                    url=page_url,
                    snippet=" | ".join(snippet_parts),
                    source="unsplash.com",
                    rank=i,
                    provider=self.name,
                    published_date=self._iso_date_prefix(item.get("created_at")),
                    extra={
                        "thumbnail_url": urls.get("thumb") or "",
                        "image_url": urls.get("regular") or "",
                        "raw_url": urls.get("raw") or "",
                        "author": author,
                        "width": width,
                        "height": height,
                        "color": item.get("color") or "",
                        "tags": [
                            tag.get("title", "")
                            for tag in (item.get("tags") or [])
                            if tag.get("title")
                        ],
                    },
                ),
            )

        return ProviderResult(results=results)
