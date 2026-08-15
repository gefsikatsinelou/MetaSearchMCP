"""NASA Image and Video Library search via the keyless public API.

``GET https://images-api.nasa.gov/search`` returns matching NASA imagery,
video, and audio assets as JSON. No API key or authentication is required.

Each hit carries the asset title, description, photographer, keywords,
location, media type, creation date, and preview image links. Assets live
on the NASA Images site at ``https://images.nasa.gov/details/<nasa_id>``.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://images-api.nasa.gov/search"
# The NASA API caps page size at 100 items per request.
_MAX_API_RESULTS = 50
# Keep description previews short in the snippet field.
_DESCRIPTION_PREVIEW = 300
# Landing page for an asset on the NASA Images site.
_DETAILS_URL = "https://images.nasa.gov/details"


class NasaProvider(BaseProvider):
    """Search the NASA Image and Video Library by keyword.

    Uses the official keyless ``images-api.nasa.gov`` endpoint, which requires
    no authentication and returns structured asset metadata: title,
    description, photographer, keywords, location, and preview URLs.
    """

    name = "nasa"
    description = (
        "Search NASA's Image and Video Library — space and science imagery "
        "with descriptions, keywords, and previews via the keyless NASA API."
    )
    tags: ClassVar[list[str]] = ["image", "media", "science"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _preview_url(item: dict[str, Any]) -> str:
        """Return the preview (thumbnail) image link for an asset item.

        Prefers the link flagged ``rel == "preview"``; falls back to the
        first link with an href when no explicit preview link exists.
        """
        links = item.get("links") or []
        preview_candidates: list[str] = []
        for link in links:
            href = (link or {}).get("href")
            if not href:
                continue
            href_str = str(href)
            if (link or {}).get("rel") == "preview":
                preview_candidates.insert(0, href_str)
            else:
                preview_candidates.append(href_str)
        return preview_candidates[0] if preview_candidates else ""

    def _parse(self, data: Any) -> ProviderResult:
        """Parse the /search response into structured search results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        collection = data.get("collection")
        if not isinstance(collection, dict):
            return ProviderResult(results=results)

        items = collection.get("items")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        for i, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            metadata_list = item.get("data")
            if not isinstance(metadata_list, list) or not metadata_list:
                continue
            metadata = metadata_list[0]
            if not isinstance(metadata, dict):
                continue

            nasa_id = str(metadata.get("nasa_id") or "")
            title = self._clean(metadata.get("title"))
            if not nasa_id or not title:
                continue

            description = self._clean(metadata.get("description"))
            photographer = self._clean(metadata.get("photographer"))
            location = self._clean(metadata.get("location"))
            keywords = [str(k) for k in (metadata.get("keywords") or []) if k]
            media_type = str(metadata.get("media_type") or "image")
            preview = self._preview_url(item)

            snippet_parts: list[str] = []
            if description:
                snippet_parts.append(description[:_DESCRIPTION_PREVIEW])
            if photographer:
                snippet_parts.append(f"Photographer: {photographer}")
            if location:
                snippet_parts.append(f"Location: {location}")
            if media_type and media_type != "image":
                snippet_parts.append(f"Media: {media_type}")

            results.append(
                SearchResult(
                    title=title,
                    url=f"{_DETAILS_URL}/{quote(nasa_id)}",
                    snippet=" | ".join(snippet_parts),
                    source="images.nasa.gov",
                    rank=i,
                    provider=self.name,
                    published_date=self._iso_date_prefix(
                        metadata.get("date_created"),
                    ),
                    extra={
                        "nasa_id": nasa_id,
                        "media_type": media_type,
                        "photographer": photographer,
                        "location": location,
                        "keywords": keywords,
                        "center": self._clean(metadata.get("center")),
                        "preview_url": preview,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search NASA's Image and Video Library for assets matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={
                    "q": query,
                    "media_type": "image,video",
                    "page_size": str(limit),
                },
            )
            resp.raise_for_status()
            data = resp.json()

        result = self._parse(data)
        # Truncate to the requested limit (the API may return page_size items).
        result.results = result.results[:limit]
        return result
