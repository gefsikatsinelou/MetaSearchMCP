"""Open VSX Registry (VS Code / Theia / Eclipse IDE extension marketplace) search.

Open VSX is the open-source, vendor-neutral registry for Visual Studio Code,
Eclipse Theia, and other VS Code-compatible editors (VSCodium ships with it
pre-configured).  Its read-only search endpoint requires no key:

``GET https://open-vsx.org/api/-/search?query=QUERY&size=N``

The endpoint returns extension records carrying the extension id
(namespace.name), display name, description, version, download count,
average rating, review count, verification status, and an icon URL.
Each hit links to the canonical ``open-vsx.org/extension/NAMESPACE/NAME``
landing page. Because the API's default ordering is relevance-based and
not guaranteed to surface the canonical extension first, hits are
re-ranked by download count so the most-used extension for a query
appears first — e.g. searching for ``python`` surfaces Microsoft's
official Python extension rather than a niche fork.

Open VSX complements the existing registry/IDE providers (JetBrains
Marketplace, Flathub, npm, PyPI, ...) by covering the open-source VS
Code-compatible ecosystem.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_SEARCH_URL = "https://open-vsx.org/api/-/search"
# The API caps page size at this value.
_MAX_API_RESULTS = 50
_EXTENSION_SOURCE = "open-vsx.org"


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _as_float(value: object) -> float | None:
    """Return *value* as a float, or None for missing/non-numeric input."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


class OpenVsxProvider(BaseProvider):
    """Search extensions on the Open VSX Registry.

    Keyless. Uses the official ``/api/-/search`` endpoint covering the
    whole Open VSX catalog. Hits are re-ranked by download count so the
    most popular (canonical) extension for a query surfaces first. Each
    hit carries the extension id, display name, description, version,
    downloads, rating, review count, verification status and icon,
    linked to the canonical Open VSX landing page.
    """

    name = "open_vsx"
    description = (
        "Search VS Code-compatible extensions on Open VSX, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "plugins"]

    @staticmethod
    def _sort_key(item: dict[str, Any]) -> tuple[int, str]:
        """Return the ordering key for one search hit.

        Higher-download extensions first (canonical extensions outrank
        obscure forks); stable tie-break by extension id.
        """
        downloads = item.get("downloadCount") or 0
        if isinstance(downloads, bool) or not isinstance(downloads, int):
            downloads = 0
        extension_id = _clean(item.get("namespace")) + "/" + _clean(item.get("name"))
        return (-downloads, extension_id)

    @staticmethod
    def _published_date(item: dict[str, Any]) -> str | None:
        """Extract a YYYY-MM-DD date from the ISO-format *timestamp* field."""
        raw = item.get("timestamp")
        if not isinstance(raw, str) or not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            return None

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse an Open VSX search response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        extensions = data.get("extensions")
        if not isinstance(extensions, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in sorted(
            (entry for entry in extensions if isinstance(entry, dict)),
            key=self._sort_key,
        )[:max_results]:
            display_name = _clean(item.get("displayName"))
            name = _clean(item.get("name"))
            namespace = _clean(item.get("namespace"))
            extension_id = f"{namespace}.{name}" if namespace and name else ""
            title = display_name or extension_id
            if not title:
                continue

            description = _clean(item.get("description"))
            version = _clean(item.get("version"))
            rating = _as_float(item.get("averageRating"))
            review_count = item.get("reviewCount") or 0
            if isinstance(review_count, bool) or not isinstance(review_count, int):
                review_count = 0
            downloads = item.get("downloadCount") or 0
            if isinstance(downloads, bool) or not isinstance(downloads, int):
                downloads = 0
            verified = bool(item.get("verified"))

            if namespace and name:
                canonical = f"https://open-vsx.org/extension/{namespace}/{name}"
            else:
                canonical = "https://open-vsx.org"

            snippet_parts: list[str] = []
            if description:
                snippet_parts.append(description)
            if version:
                snippet_parts.append(f"v{version}")
            if downloads:
                snippet_parts.append(f"Downloads: {downloads:,}")
            if rating is not None:
                snippet_parts.append(f"Rating: {rating:.2f}")
            if review_count:
                snippet_parts.append(f"Reviews: {review_count}")
            publisher_label = (
                "Verified publisher" if verified else "Unverified publisher"
            )
            snippet_parts.append(publisher_label)
            if not snippet_parts:
                snippet_parts.append("Open VSX extension")

            files = item.get("files")
            icon = ""
            if isinstance(files, dict):
                icon = _clean(files.get("icon"))

            results.append(
                SearchResult(
                    title=title,
                    url=canonical,
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source=_EXTENSION_SOURCE,
                    published_date=self._published_date(item),
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "extension_id": extension_id,
                        "namespace": namespace,
                        "name": name,
                        "display_name": display_name,
                        "description": description,
                        "version": version,
                        "downloads": downloads,
                        "rating": round(rating, 2) if rating is not None else None,
                        "review_count": review_count,
                        "verified": verified,
                        "icon": icon,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the Open VSX Registry for extensions matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _API_SEARCH_URL,
                params={"query": query, "size": limit},
            )
            resp.raise_for_status()
            data = resp.json()
        return self._parse(data, limit=limit)
