"""Cleveland Museum of Art collection search via the keyless public API.

``GET https://openaccess-api.clevelandart.org/api/artworks/`` returns
matching artworks from the Cleveland Museum of Art's open-access collection
as JSON. No API key or authentication is required.

The search endpoint returns rich artwork metadata directly (title, artist,
date, technique, department, type, and image URLs), so — like the Art
Institute of Chicago provider — no per-object follow-up fetches are needed.
A ``fields`` parameter keeps the response payload small. Each result links
to the artwork page on clevelandart.org; the web-resolution image is served
from the open-access CDN.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://openaccess-api.clevelandart.org/api/artworks/"
# The CMA API caps page size at 100 items per request.
_MAX_API_RESULTS = 50
# Fields returned for each artwork, keeping the response payload small.
_FIELDS = (
    "id,title,creators,creation_date,technique,department,type,url,"
    "images,creditline,accession_number"
)


class ClevelandArtProvider(BaseProvider):
    """Search artworks in the Cleveland Museum of Art collection.

    Uses the keyless open-access API, which requires no authentication and
    returns structured artwork metadata: title, artist, date, technique,
    department, and image URLs.
    """

    name = "clevelandart"
    description = (
        "Search the Cleveland Museum of Art open-access collection — artist, "
        "date, medium, and image via the keyless CMA API."
    )
    tags: ClassVar[list[str]] = ["art", "images", "media"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _image_url(images: object) -> str:
        """Return the web-resolution image URL for an artwork, or ''."""
        if not isinstance(images, dict):
            return ""
        web = images.get("web")
        if isinstance(web, dict) and web.get("url"):
            return str(web["url"])
        # Fall back to the print-resolution image when web is unavailable.
        print_image = images.get("print")
        if isinstance(print_image, dict) and print_image.get("url"):
            return str(print_image["url"])
        return ""

    def _parse(self, data: Any, limit: int | None = None) -> ProviderResult:
        """Parse the /api/artworks/ response into structured results."""
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
            image_url = self._image_url(item.get("images"))
            # Skip artworks without a usable image (not useful for art search).
            if not title or not image_url:
                continue

            artist = ""
            for creator in item.get("creators") or []:
                if not isinstance(creator, dict):
                    continue
                description = self._clean(creator.get("description"))
                if description:
                    artist = description
                    break
            date = self._clean(item.get("creation_date"))
            technique = self._clean(item.get("technique"))
            department = self._clean(item.get("department"))
            artwork_type = self._clean(item.get("type"))
            creditline = self._clean(item.get("creditline"))

            snippet_parts: list[str] = []
            if artist:
                snippet_parts.append(artist)
            if date:
                snippet_parts.append(date)
            if department:
                snippet_parts.append(department)
            if artwork_type:
                snippet_parts.append(artwork_type)
            if technique:
                snippet_parts.append(f"Medium: {technique}")

            results.append(
                SearchResult(
                    title=title,
                    url=str(item.get("url") or ""),
                    snippet=" | ".join(snippet_parts),
                    source="clevelandart.org",
                    rank=i,
                    provider=self.name,
                    extra={
                        "artist": artist,
                        "date": date,
                        "technique": technique,
                        "department": department,
                        "type": artwork_type,
                        "accession_number": self._clean(item.get("accession_number")),
                        "creditline": creditline,
                        "image_url": image_url,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the CMA collection for artworks matching *query*."""
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
