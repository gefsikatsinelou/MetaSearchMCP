"""Wikimedia Commons image search via the public MediaWiki API.

Wikimedia Commons hosts over 100 million freely licensed media files.
Searching requires no API key; results include thumbnail URLs, image
dimensions, and license information.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar
from urllib.parse import urlsplit, urlunsplit

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://commons.wikimedia.org/w/api.php"
# File namespace on Commons (searching it restricts results to media files).
_FILE_NAMESPACE = "6"
_API_MAX_RESULTS = 30
_THUMB_WIDTH = 400


class WikimediaCommonsProvider(BaseProvider):
    """Search freely licensed images and media on Wikimedia Commons.

    Uses the MediaWiki ``generator=search`` API in a single request:
    file pages matching the query are returned together with their
    imageinfo (thumbnail URL, dimensions, license, author).
    """

    name = "wikimedia_commons"
    description = "Search freely licensed images and media on Wikimedia Commons."
    tags: ClassVar[list[str]] = ["image", "media", "knowledge"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Wikimedia Commons for media files matching *query*."""
        limit = min(params.num_results, self._max_results, _API_MAX_RESULTS)
        payload = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": _FILE_NAMESPACE,
            "gsrlimit": str(limit),
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
            "iiurlwidth": str(_THUMB_WIDTH),
            "format": "json",
            "origin": "*",
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    @staticmethod
    def _clean_metadata(value: object) -> str:
        """Strip HTML tags and collapse whitespace in an extmetadata value."""
        if not value:
            return ""
        text = re.sub(r"<[^>]+>", "", str(value))
        return " ".join(text.split())

    @staticmethod
    def _strip_tracking_params(url: str) -> str:
        """Remove UTM tracking query parameters added by the MediaWiki API."""
        parts = urlsplit(url)
        if not parts.query:
            return url
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the MediaWiki API response into structured search results."""
        pages = data.get("query", {}).get("pages", {}) or {}
        results: list[SearchResult] = []

        for i, page in enumerate(
            sorted(pages.values(), key=lambda p: p.get("index", 0)),
            start=1,
        ):
            info = (page.get("imageinfo") or [{}])[0]
            if not info.get("thumburl"):
                continue

            title = page.get("title", "")
            display_title = title[5:] if title.startswith("File:") else title
            url = info.get("descriptionurl") or info.get("url") or ""
            width = info.get("width")
            height = info.get("height")
            ext = info.get("extmetadata", {})
            license_name = self._clean_metadata(
                ext.get("LicenseShortName", {}).get("value"),
            )
            author = self._clean_metadata(ext.get("Artist", {}).get("value"))
            date_raw = ext.get("DateTimeOriginal", {}).get("value") or ""

            snippet_parts: list[str] = []
            if width and height:
                snippet_parts.append(f"{width}x{height}px")
            if license_name:
                snippet_parts.append(f"License: {license_name}")
            if author:
                snippet_parts.append(f"Author: {author}")

            results.append(
                SearchResult(
                    title=display_title,
                    url=url,
                    snippet=" | ".join(snippet_parts),
                    source="commons.wikimedia.org",
                    rank=i,
                    provider=self.name,
                    published_date=self._iso_date_prefix(date_raw),
                    extra={
                        "thumbnail_url": self._strip_tracking_params(
                            info.get("thumburl") or "",
                        ),
                        "image_url": info.get("url") or "",
                        "width": width,
                        "height": height,
                        "license": license_name,
                        "author": author,
                    },
                ),
            )

        return ProviderResult(results=results)
