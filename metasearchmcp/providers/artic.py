"""Art Institute of Chicago collection search via the keyless public API.

``GET https://api.artic.edu/api/v1/artworks/search`` returns matching
artworks from the Art Institute of Chicago's public collection as JSON.
No API key or authentication is required.

The search endpoint returns rich artwork metadata directly (title, artist,
date, medium, department, and a thumbnail), so unlike the Met Museum
provider no per-object follow-up fetches are needed. A ``fields``
parameter keeps the payload small. Each result links to the artwork page
on artic.edu; the full-size image is available through the IIIF endpoint
at ``https://www.artic.edu/iiif/2/{image_id}/full/843,/0/default.jpg``.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://api.artic.edu/api/v1/artworks/search"
# The AIC API caps page size at 100 items per request.
_MAX_API_RESULTS = 50
# Fields returned for each artwork, keeping the response payload small.
_FIELDS = (
    "id,title,artist_title,date_display,medium_display,"
    "department_title,image_id,thumbnail,api_link"
)
# IIIF image server prefix used to build full-size image URLs.
_IIIF_URL = "https://www.artic.edu/iiif/2"
# Full-size image rendering size (longest edge).
_IIIF_SIZE = "843,"


class ArticProvider(BaseProvider):
    """Search artworks in the Art Institute of Chicago collection.

    Uses the keyless public API, which requires no authentication and
    returns structured artwork metadata: title, artist, date, medium,
    department, and a thumbnail image.
    """

    name = "artic"
    description = (
        "Search the Art Institute of Chicago public collection — artist, "
        "date, medium, and image via the keyless AIC API."
    )
    tags: ClassVar[list[str]] = ["art", "image", "media"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _image_url(image_id: object) -> str:
        """Build the IIIF full-size image URL for an artwork, or ''."""
        if not image_id:
            return ""
        image_id_str = str(image_id)
        if not image_id_str.startswith("/"):
            image_id_str = f"/{image_id_str}"
        return f"{_IIIF_URL}{image_id_str}/full/{_IIIF_SIZE}/0/default.jpg"

    def _parse(self, data: Any, limit: int | None = None) -> ProviderResult:
        """Parse the /artworks/search response into structured results."""
        results: list[SearchResult] = []
        max_results = limit or self._max_results
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        items = data.get("data")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        for i, item in enumerate(items, start=1):
            if i > max_results:
                break
            if not isinstance(item, dict):
                continue

            title = self._clean(item.get("title"))
            if not title:
                continue

            artist = self._clean(item.get("artist_title"))
            date = self._clean(item.get("date_display"))
            medium = self._clean(item.get("medium_display"))
            department = self._clean(item.get("department_title"))

            snippet_parts: list[str] = []
            if artist:
                snippet_parts.append(artist)
            if date:
                snippet_parts.append(date)
            if department:
                snippet_parts.append(department)
            if medium:
                snippet_parts.append(f"Medium: {medium}")

            thumbnail = item.get("thumbnail")
            if not isinstance(thumbnail, dict):
                thumbnail = {}
            alt_text = self._clean(thumbnail.get("alt_text"))

            results.append(
                SearchResult(
                    title=title,
                    url=str(item.get("api_link") or ""),
                    snippet=" | ".join(snippet_parts),
                    source="artic.edu",
                    rank=i,
                    provider=self.name,
                    extra={
                        "artist": artist,
                        "date": date,
                        "medium": medium,
                        "department": department,
                        "image_id": str(item.get("image_id") or ""),
                        "image_url": self._image_url(item.get("image_id")),
                        "thumbnail_url": str(thumbnail.get("lqip") or ""),
                        "alt_text": alt_text,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the AIC collection for artworks matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={
                    "q": query,
                    "limit": str(limit),
                    "fields": _FIELDS,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit)
