"""The Met Museum collection search via the public, keyless API.

``GET https://collectionapi.metmuseum.org/public/collection/v1/search``
returns matching object IDs from the Metropolitan Museum of Art's public
collection as JSON. No API key or authentication is required.

The search endpoint only returns a flat list of object IDs, so each object's
metadata (title, artist, date, medium, thumbnail, etc.) is fetched from the
per-object endpoint ``/public/collection/v1/objects/{id}``.  ``total`` is 0
when nothing matches the query.

Note: the museum API is free and open; results are best-effort and the
search matches object titles, artists, and other catalog fields.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_SEARCH_URL = "https://collectionapi.metmuseum.org/public/collection/v1/search"
_OBJECT_URL = (
    "https://collectionapi.metmuseum.org/public/collection/v1/objects/{object_id}"
)
# Fetch at most this many object details per search request.
_MAX_OBJECT_FETCHES = 20
# The per-object endpoint is hit once per result; keep a small cap on latency.
_OBJECT_FETCH_TIMEOUT = 10.0


class MetMuseumProvider(BaseProvider):
    """Search artworks in the Metropolitan Museum of Art collection.

    Uses the keyless public API, which requires no authentication and returns
    structured artwork metadata: title, artist, date, medium, department,
    and a thumbnail image.
    """

    name = "metmuseum"
    description = (
        "Search the Metropolitan Museum of Art public collection — artist, "
        "date, medium, and thumbnail via the keyless Met API."
    )
    tags: ClassVar[list[str]] = ["art", "images", "media"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    async def _fetch_object(self, client: Any, object_id: int) -> dict[str, Any] | None:
        """Fetch metadata for a single object; ``None`` on failure or no image."""
        try:
            resp = await client.get(_OBJECT_URL.format(object_id=object_id))
            resp.raise_for_status()
        except Exception:
            return None
        try:
            data = resp.json()
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        # Skip objects without a primary image (not useful for art search).
        if not data.get("primaryImage"):
            return None
        return data

    def _parse_object(
        self, object_id: int, data: dict[str, Any], rank: int
    ) -> SearchResult | None:
        """Build a SearchResult from an object's metadata dict."""
        title = self._clean_text(data.get("title"))
        if not title:
            return None

        artist = self._clean_text(data.get("artistDisplayName"))
        date = self._clean_text(data.get("objectDate"))
        medium = self._clean_text(data.get("medium"))
        department = self._clean_text(data.get("department"))

        snippet_parts: list[str] = []
        if artist:
            snippet_parts.append(artist)
        if date:
            snippet_parts.append(date)
        if department:
            snippet_parts.append(department)
        if medium:
            snippet_parts.append(f"Medium: {medium}")

        return SearchResult(
            title=title,
            url=f"https://www.metmuseum.org/art/collection/search/{object_id}",
            snippet=" | ".join(snippet_parts),
            source="metmuseum.org",
            rank=rank,
            provider=self.name,
            extra={
                "object_id": object_id,
                "artist": artist,
                "date": date,
                "medium": medium,
                "department": department,
                "thumbnail_url": str(data.get("primaryImageSmall") or ""),
            },
        )

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the Met collection for artworks matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_OBJECT_FETCHES)
        async with self._client() as client:
            resp = await client.get(
                _SEARCH_URL, params={"q": query, "hasImages": "true"}
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[SearchResult] = []
        object_ids = data.get("objectIDs") if isinstance(data, dict) else None
        if not isinstance(object_ids, list):
            return ProviderResult(results=results)

        # The search endpoint only returns IDs; fetch details per object.
        async with self._client() as client:
            for object_id in object_ids[:limit]:
                obj = await self._fetch_object(client, object_id)
                if obj is None:
                    continue
                result = self._parse_object(object_id, obj, len(results) + 1)
                if result is not None:
                    results.append(result)

        return ProviderResult(results=results)
