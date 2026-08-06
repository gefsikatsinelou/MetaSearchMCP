"""Openverse openly licensed image search via the public, keyless REST API.

Openverse (openverse.org, a WordPress project) aggregates over 700 million
openly licensed images from Flickr, Wikimedia Commons, and other sources.
Its public API requires no API key for anonymous use:

``GET https://api.openverse.org/v1/images/?q=QUERY&page_size=N``

Each hit includes the title, landing-page URL, direct image URL, thumbnail,
creator, license, and dimensions. Parsing uses the standard library plus the
shared httpx client from the base provider.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://api.openverse.org/v1/images"
# Openverse caps a single listing request at this many items.
_MAX_API_RESULTS = 50


class OpenverseProvider(BaseProvider):
    """Search openly licensed images across the Openverse catalog.

    Uses the keyless public REST API, which aggregates openly licensed
    images from Flickr, Wikimedia Commons, and other sources. Each hit
    carries the title, landing page, direct image URL, thumbnail, creator,
    license, and dimensions.
    """

    name = "openverse"
    description = (
        "Search openly licensed images across Openverse (Flickr, Wikimedia, and more)."
    )
    tags: ClassVar[list[str]] = ["image", "media"]

    @staticmethod
    def _clean_text(value: Any) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _license_label(license_name: Any, version: Any) -> str:
        """Build a short human-readable license label like ``CC BY 4.0``."""
        name = str(license_name or "").strip().upper()
        if not name:
            return ""
        label = f"CC {name}"
        if version:
            label = f"{label} {version}"
        return label

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the Openverse API response into structured search results."""
        results: list[SearchResult] = []
        items = data.get("results") or []

        for i, item in enumerate(items, start=1):
            landing_url = item.get("foreign_landing_url") or ""
            direct_url = item.get("url") or ""
            if not landing_url and not direct_url:
                continue

            title = self._clean_text(item.get("title"))
            creator = self._clean_text(item.get("creator"))
            license_label = self._license_label(
                item.get("license"),
                item.get("license_version"),
            )
            width = item.get("width")
            height = item.get("height")

            snippet_parts: list[str] = []
            if width and height:
                snippet_parts.append(f"{width}x{height}px")
            if license_label:
                snippet_parts.append(f"License: {license_label}")
            if creator:
                snippet_parts.append(f"Author: {creator}")
            if item.get("provider"):
                snippet_parts.append(f"Source: {item.get('provider')}")

            results.append(
                SearchResult(
                    title=title or (landing_url or direct_url),
                    url=landing_url or direct_url,
                    snippet=" | ".join(snippet_parts),
                    source="openverse.org",
                    rank=i,
                    provider=self.name,
                    published_date=self._iso_date_prefix(item.get("indexed_on")),
                    extra={
                        "thumbnail_url": item.get("thumbnail") or "",
                        "image_url": direct_url,
                        "landing_url": landing_url,
                        "width": width,
                        "height": height,
                        "license": license_label,
                        "license_url": item.get("license_url") or "",
                        "author": creator,
                        "author_url": item.get("creator_url") or "",
                        "source_provider": item.get("provider") or "",
                        "mature": bool(item.get("mature", False)),
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Openverse for openly licensed images matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {
            "q": query,
            "page_size": str(limit),
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)
