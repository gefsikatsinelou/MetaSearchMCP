"""Flathub (Linux desktop app distribution) search via the official keyless API.

Flathub is the central app store for the Flatpak/Linux desktop application
ecosystem, hosting thousands of sandboxed apps (Obsidian, GIMP, Blender,
Spotify, OBS Studio, ...).  Its read-only search endpoint requires no key:

``POST https://flathub.org/api/v2/search``
    body: {"query": QUERY, "limit": N}

The endpoint returns per-app records carrying the app id, name, summary,
description, developer, license, icon, and rich popularity metadata
(installs_last_month, favorites_count, trending, verification status).
Each hit links to the canonical ``flathub.org/apps/APP_ID`` landing page.
Flathub complements the existing registry providers (Docker Hub, Steam,
npm, PyPI, ...) which cover container images and other ecosystems but not
the Linux desktop application universe.
"""

from __future__ import annotations

from typing import ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_SEARCH_URL = "https://flathub.org/api/v2/search"
_CANONICAL_URL = "https://flathub.org/apps"
# The API ignores limits above this value.
_MAX_API_RESULTS = 50


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


class FlathubProvider(BaseProvider):
    """Search Linux desktop apps distributed through Flathub.

    Keyless. Uses the official ``/api/v2/search`` endpoint, which covers
    the whole Flathub catalog. Hits are ordered by the API's relevance
    ranking; each hit carries the app id, name, summary, developer,
    license, icon, installs/favorites popularity and verification status,
    linked to the canonical Flathub landing page.
    """

    name = "flathub"
    description = "Search Linux desktop apps on Flathub, no API key required."
    tags: ClassVar[list[str]] = ["web", "code", "developer", "apps"]

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a Flathub search response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        hits = data.get("hits")
        if not isinstance(hits, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in hits[:max_results]:
            if not isinstance(item, dict):
                continue
            name = _clean(item.get("name"))
            app_id = _clean(item.get("app_id"))
            if not name and not app_id:
                continue

            app_id = app_id or name
            summary = _clean(item.get("summary"))
            description = _clean(item.get("description"))
            developer = _clean(item.get("developer_name")) or _clean(
                item.get("developer")
            )
            license_text = _clean(item.get("project_license"))
            icon = _clean(item.get("icon"))
            installs = item.get("installs_last_month") or 0
            favorites = item.get("favorites_count") or 0

            snippet_parts: list[str] = []
            if summary:
                snippet_parts.append(summary)
            if developer:
                snippet_parts.append(f"Developer: {developer}")
            if license_text:
                snippet_parts.append(f"License: {license_text}")
            if installs:
                snippet_parts.append(f"Installs/mo: {int(installs):,}")
            if not snippet_parts and description:
                snippet_parts.append(description[:MAX_SNIPPET_LENGTH])
            if not snippet_parts:
                snippet_parts.append("Flatpak desktop application")

            results.append(
                SearchResult(
                    title=f"{name} ({app_id})" if name != app_id else app_id,
                    url=f"{_CANONICAL_URL}/{app_id}",
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source="flathub.org",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "app_id": app_id,
                        "name": name,
                        "summary": summary,
                        "description": description,
                        "developer": developer,
                        "license": license_text,
                        "installs_last_month": int(installs),
                        "favorites_count": int(favorites),
                        "icon": icon,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Flathub for desktop apps matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {"query": query, "limit": limit}
        headers = {"Content-Type": "application/json"}
        async with self._client() as client:
            resp = await client.post(_API_SEARCH_URL, json=payload, headers=headers)
            if resp.status_code == 404:
                # Very old Flathub versions may not expose the v2 search
                # endpoint; fail gracefully instead of raising.
                return ProviderResult(results=[])
            resp.raise_for_status()
            data = resp.json()
        return self._parse(data, limit=limit)
