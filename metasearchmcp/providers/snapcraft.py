"""Snapcraft (Snap Store) Linux app search via the official keyless API.

Snapcraft is the app store of the snap packaging ecosystem, used by
Ubuntu and dozens of other Linux distributions to distribute thousands
of desktop and CLI applications (Firefox, Obsidian, Spotify, Slack,
VS Code, ...).  Its read-only search endpoint requires no key:

``GET https://api.snapcraft.io/v2/snaps/find?q=QUERY&fields=...``
    headers: {"Snap-Device-Series": "16"}

The endpoint returns per-snap records carrying the snap slug, title,
summary, description, publisher, license, version, base/confinement and
category metadata, plus icon media.  Each hit links to the canonical
``snapcraft.io/NAME`` landing page.  Snapcraft complements the existing
Flathub provider: together they cover the two dominant Linux desktop
app stores (snap vs Flatpak).
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_SEARCH_URL = "https://api.snapcraft.io/v2/snaps/find"
_CANONICAL_URL = "https://snapcraft.io"
# The /find endpoint does not accept a page-size parameter, so slicing
# is capped defensively at the store's default page size.
_MAX_API_RESULTS = 25
# Required device-series header (value "16" = generic Linux desktop).
_DEVICE_SERIES = "16"
# Fields requested from the API; title/summary/... arrive under "snap"
# while version/base/confinement arrive under "revision".
_API_FIELDS = (
    "title,summary,description,media,store-url,publisher,license,"
    "categories,version,base,confinement"
)


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _string(value: object) -> str:
    """Return a cleaned string, or ``""`` for non-string values."""
    return _clean(value) if isinstance(value, str) else ""


class SnapcraftProvider(BaseProvider):
    """Search Linux desktop applications distributed as snaps.

    Keyless. Uses the official Snap Store v2 ``/snaps/find`` endpoint,
    which covers the whole Snapcraft catalog.  Hits are ordered by the
    store's relevance ranking; each hit carries the snap slug, title,
    summary, publisher, license, version, confinement and categories,
    linked to the canonical Snapcraft landing page.
    """

    name = "snapcraft"
    description = (
        "Search Linux desktop apps on Snapcraft (Snap Store), no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "apps"]

    @staticmethod
    def _first_icon(media: object) -> str:
        """Return the first icon media URL from the API media list."""
        if not isinstance(media, list):
            return ""
        for entry in media:
            if isinstance(entry, dict) and entry.get("type") == "icon":
                icon = _string(entry.get("url"))
                if icon:
                    return icon
        return ""

    @staticmethod
    def _category_names(categories: object) -> list[str]:
        """Extract the unique category names from the API category objects."""
        names: list[str] = []
        if isinstance(categories, list):
            for entry in categories:
                if isinstance(entry, dict):
                    name = _string(entry.get("name"))
                    if name and name not in names:
                        names.append(name)
        return names

    @staticmethod
    def _publisher_name(publisher: object) -> str:
        """Return the publisher display name from the API publisher object."""
        if isinstance(publisher, dict):
            return _string(publisher.get("display-name"))
        return ""

    def _parse(self, data: Any, limit: int | None = None) -> ProviderResult:
        """Parse a Snapcraft find response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        hits = data.get("results")
        if not isinstance(hits, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in hits[:max_results]:
            if not isinstance(item, dict):
                continue
            snap = item.get("snap")
            if not isinstance(snap, dict):
                continue

            slug = _string(item.get("name"))
            title = _string(snap.get("title")) or slug
            if not title:
                continue
            store_url = _string(snap.get("store-url"))
            if not store_url:
                store_url = f"{_CANONICAL_URL}/{slug}" if slug else ""
            if not store_url:
                continue

            revision = item.get("revision")
            version = (
                _string(revision.get("version")) if isinstance(revision, dict) else ""
            )
            summary = _string(snap.get("summary"))
            description = _string(snap.get("description"))
            license_text = _string(snap.get("license"))
            publisher = self._publisher_name(snap.get("publisher"))
            categories = self._category_names(snap.get("categories"))
            confinement = (
                _string(revision.get("confinement"))
                if isinstance(revision, dict)
                else ""
            )
            icon = self._first_icon(snap.get("media"))

            snippet_parts: list[str] = []
            if summary:
                snippet_parts.append(summary)
            if publisher:
                snippet_parts.append(f"Publisher: {publisher}")
            if version:
                snippet_parts.append(f"Version: {version}")
            if license_text:
                snippet_parts.append(f"License: {license_text}")
            if categories:
                snippet_parts.append(f"Categories: {', '.join(categories)}")
            if not snippet_parts and description:
                snippet_parts.append(description[:MAX_SNIPPET_LENGTH])
            if not snippet_parts:
                snippet_parts.append("Snap (Linux desktop app)")

            display_title = f"{title} ({slug})" if title != slug else slug
            results.append(
                SearchResult(
                    title=display_title,
                    url=store_url,
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source="snapcraft.io",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "snap_id": _string(item.get("snap-id")),
                        "slug": slug,
                        "title": title,
                        "summary": summary,
                        "description": description,
                        "publisher": publisher,
                        "version": version,
                        "license": license_text,
                        "categories": categories,
                        "confinement": confinement,
                        "icon": icon,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the Snap Store for snaps matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        headers = {"Snap-Device-Series": _DEVICE_SERIES}
        request_params = {"q": query, "fields": _API_FIELDS}
        async with self._client() as client:
            resp = await client.get(
                _API_SEARCH_URL,
                params=request_params,
                headers=headers,
            )
            if resp.status_code == 404:
                # The v2 find endpoint is not always exposed; fail gracefully.
                return ProviderResult(results=[])
            resp.raise_for_status()
            data = resp.json()
        return self._parse(data, limit=limit)
