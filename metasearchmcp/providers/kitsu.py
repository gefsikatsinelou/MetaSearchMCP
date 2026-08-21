"""Kitsu anime and manga search via the public, keyless Kitsu API.

Kitsu is a community-driven catalog of anime and manga. Its public
JSON:API endpoint supports text search over both media types without
any API key:

``GET https://kitsu.io/api/edge/anime?filter[text]=QUERY&page[limit]=N``

Each hit includes the canonical title, synopsis, start/end dates,
status (current/finished), episode count, average rating, genres via
the categories relationship, and a poster image URL. The manga endpoint
follows the same shape with chapter/volume counts.

No API key or authentication is required; parsing uses only the shared
httpx client from the base provider. The API is rate-limited to 60
requests/minute for unauthenticated clients.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_BASE = "https://kitsu.io/api/edge"
# Per-type search endpoint suffix (anime or manga).
_TYPE_ENDPOINTS: dict[str, str] = {
    "anime": f"{_API_BASE}/anime",
    "manga": f"{_API_BASE}/manga",
}
# Kitsu caps a single page at this many results.
_MAX_API_RESULTS = 20
# Relationship -> API key the response includes per media item.
_RELATIONSHIP_KEYS: dict[str, str] = {
    "genres": "categories",
    "studio": "producers",
}
# Which media types are searched, in priority order.
_MEDIA_TYPES: tuple[str, ...] = ("anime", "manga")
# JSON:API responses use Accept: application/vnd.api+json.
_JSON_API_HEADERS = {"Accept": "application/vnd.api+json"}


class KitsuProvider(BaseProvider):
    """Search anime and manga across the Kitsu community catalog.

    Uses the keyless public JSON:API. Each hit carries the canonical
    title, synopsis, dates, status, episode/chapter counts, average
    rating, genres, and a poster image URL.
    """

    name = "kitsu"
    description = (
        "Search anime and manga in the Kitsu community catalog, no API key required."
    )
    tags: ClassVar[list[str]] = ["anime", "manga", "media"]

    @staticmethod
    def _relationship_names(item: dict[str, Any], key: str) -> list[str]:
        """Return related category/producer names from a JSON:API item."""
        relationships = item.get("relationships") or {}
        relation = relationships.get(key) or {}
        data = relation.get("data") or []
        if not isinstance(data, list):
            return []
        return [str(entry.get("id", "")) for entry in data if isinstance(entry, dict)]

    @staticmethod
    def _poster_url(attributes: dict[str, Any]) -> str:
        """Return the medium-sized poster image URL, or empty string."""
        poster = attributes.get("posterImage")
        if isinstance(poster, dict):
            for size in ("medium", "small", "original"):
                url = poster.get(size)
                if url:
                    return str(url)
        return ""

    def _parse(self, data: dict[str, Any], media_type: str) -> ProviderResult:
        """Parse a Kitsu JSON:API response into structured search results."""
        results: list[SearchResult] = []
        for i, item in enumerate(data.get("data") or [], start=1):
            if not isinstance(item, dict):
                continue
            attributes = item.get("attributes") or {}
            title = attributes.get("canonicalTitle") or attributes.get("slug") or ""
            url = item.get("links", {}).get("self") or ""
            # Skip items without any usable identifier: the second entry in
            # _SAMPLE_ANIME has only a slug and no links, so it is dropped.
            if not title or not url:
                continue

            synopsis = " ".join(str(attributes.get("synopsis") or "").split())
            meta_parts: list[str] = []
            if media_type == "anime":
                episodes = attributes.get("episodeCount")
                if episodes:
                    meta_parts.append(f"Episodes: {episodes}")
            else:
                chapters = attributes.get("chapterCount")
                if chapters:
                    meta_parts.append(f"Chapters: {chapters}")
            rating = attributes.get("averageRating")
            if rating:
                meta_parts.append(f"Rating: {rating}")
            status = attributes.get("status")
            if status:
                meta_parts.append(f"Status: {status.capitalize()}")
            genres = self._relationship_names(item, _RELATIONSHIP_KEYS["genres"])
            if genres:
                meta_parts.append(f"Genres: {', '.join(genres[:5])}")

            snippet_parts = [synopsis[:MAX_SNIPPET_LENGTH]] if synopsis else []
            if meta_parts:
                snippet_parts.append(" | ".join(meta_parts))

            poster = self._poster_url(attributes)
            extra: dict[str, Any] = {
                "media_type": media_type,
                "status": status or "",
                "average_rating": rating or "",
                "genres": genres,
                "start_date": attributes.get("startDate") or "",
                "end_date": attributes.get("endDate") or "",
            }
            if media_type == "anime":
                extra["episodes"] = attributes.get("episodeCount") or ""
                extra["episode_length"] = attributes.get("episodeLength") or ""
            else:
                extra["chapters"] = attributes.get("chapterCount") or ""
                extra["volumes"] = attributes.get("volumeCount") or ""
            if poster:
                extra["image_url"] = poster

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(snippet_parts),
                    source="kitsu.io",
                    rank=i,
                    provider=self.name,
                    published_date=attributes.get("startDate") or None,
                    extra=extra,
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search anime first, then manga, for *query* via the Kitsu API.

        Both media types are queried concurrently; the merged result set is
        capped at ``params.num_results``.
        """
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        async def _search_type(media_type: str) -> ProviderResult:
            endpoint = _TYPE_ENDPOINTS[media_type]
            payload = {"filter[text]": query, "page[limit]": str(limit)}
            async with self._client() as client:
                client.headers.update(_JSON_API_HEADERS)
                resp = await client.get(endpoint, params=payload)
                resp.raise_for_status()
                data = resp.json()
            return self._parse(data, media_type)

        payloads = await asyncio.gather(
            *(_search_type(t) for t in _MEDIA_TYPES),
            return_exceptions=True,
        )

        results: list[SearchResult] = []
        for payload in payloads:
            if isinstance(payload, Exception):
                continue
            results.extend(payload.results)
        return ProviderResult(results=results[:limit])
