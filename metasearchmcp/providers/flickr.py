"""Flickr public photo search via the keyless public feed API.

The Flickr public feed (``photos_public.gne``) returns recently uploaded
public photos matching the given tags as JSON without requiring an API key:

``GET https://www.flickr.com/services/feeds/photos_public.gne?tags=QUERY&format=json&nojsoncallback=1``

Each item includes the title, landing-page URL, thumbnail (``media.m``),
author, tags, and an HTML description. Parsing uses BeautifulSoup (already a
project dependency) to strip the description HTML, plus the shared httpx
client from the base provider.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any, ClassVar

from bs4 import BeautifulSoup

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://www.flickr.com/services/feeds/photos_public.gne"
# The public feed returns at most this many items per request.
_MAX_API_RESULTS = 20
# Matches `nobody@flickr.com ("Display Name")` in the author field.
_AUTHOR_RE = re.compile(r'"([^"]+)"')


class FlickrProvider(BaseProvider):
    """Search recently uploaded public photos on Flickr.

    Uses the keyless public feed, which requires no authentication and
    returns a snapshot of recent public uploads matching the query tags.
    Each hit carries the title, landing page, thumbnail, author, and tags.
    """

    name = "flickr"
    description = (
        "Search recent public photos on Flickr by tag — keyless public feed "
        "with thumbnails and author info."
    )
    tags: ClassVar[list[str]] = ["image", "media"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _author_name(author: object) -> str:
        """Extract the display name from a Flickr ``author`` field."""
        match = _AUTHOR_RE.search(str(author or ""))
        return unescape(match.group(1)) if match else ""

    @staticmethod
    def _snippet_from_description(description: object) -> str:
        """Extract readable text from the HTML description field."""
        html = str(description or "")
        soup = BeautifulSoup(html, "lxml")
        return " ".join(soup.get_text(" ", strip=True).split())

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the public feed response into structured search results."""
        results: list[SearchResult] = []
        items = data.get("items") or []

        for i, item in enumerate(items, start=1):
            link = item.get("link") or ""
            media = item.get("media") or {}
            thumb = media.get("m") or ""
            if not link:
                continue

            title = self._clean_text(item.get("title")) or link
            author = self._author_name(item.get("author"))
            tags = self._clean_text(item.get("tags"))
            snippet = self._snippet_from_description(item.get("description"))

            snippet_parts: list[str] = []
            if author:
                snippet_parts.append(f"Author: {author}")
            if tags:
                snippet_parts.append(f"Tags: {tags[:120]}")

            results.append(
                SearchResult(
                    title=title,
                    url=link,
                    snippet=snippet or " | ".join(snippet_parts),
                    source="flickr.com",
                    rank=i,
                    provider=self.name,
                    published_date=self._iso_date_prefix(item.get("published")),
                    extra={
                        "thumbnail_url": thumb,
                        "image_url": thumb,
                        "landing_url": link,
                        "author": author,
                        "tags": tags.split() if tags else [],
                        "date_taken": self._iso_date_prefix(item.get("date_taken")),
                    },
                ),
            )
            if i >= _MAX_API_RESULTS:
                break

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Flickr for public photos matching *query* tags."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {
            "tags": query,
            "tagmode": "all",
            "format": "json",
            "nojsoncallback": "1",
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        result = self._parse(data)
        # Truncate to the requested limit (the feed returns up to 20 items).
        result.results = result.results[:limit]
        return result
