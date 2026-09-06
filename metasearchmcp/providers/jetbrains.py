"""JetBrains Marketplace plugin search via the official keyless API.

The JetBrains Marketplace hosts plugins for the JetBrains IDEs
(IntelliJ IDEA, PyCharm, WebStorm, CLion, DataGrip, GoLand, ...).
Its read-only search endpoint requires no key:

``GET https://plugins.jetbrains.com/api/searchPlugins?search=QUERY&max=N``

The endpoint returns plugin records carrying the plugin id, xml id,
name, preview/description, download count, rating, pricing model
(FREE / paid), icon, and the vendor name plus verification status.
Each hit links to the canonical ``plugins.jetbrains.com/plugin/ID``
landing page. Because the API's default ordering is not guaranteed to
surface the canonical plugin first, hits are re-ranked by download
count so the most-used plugin for a query appears first — e.g.
searching for ``python`` yields the official Python plugin rather
than an obscure fork.  JetBrains complements the existing registry
providers (Flathub, Docker Hub, Steam, npm, PyPI, ...) by covering
the IDE/plugin ecosystem.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_SEARCH_URL = "https://plugins.jetbrains.com/api/searchPlugins"
_CANONICAL_URL = "https://plugins.jetbrains.com"
# The API caps page size at this value.
_MAX_API_RESULTS = 50
_MARKETPLACE_SOURCE = "plugins.jetbrains.com"


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _as_int(value: object) -> int:
    """Return *value* as an int, or 0 for missing/boolean/non-numeric input."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


class JetbrainsProvider(BaseProvider):
    """Search IDE plugins on the JetBrains Marketplace.

    Keyless. Uses the official ``searchPlugins`` endpoint covering the
    whole Marketplace catalog. Hits are re-ranked by download count so
    the most popular (canonical) plugin for a query surfaces first.
    Each hit carries the plugin name, preview/description, downloads,
    rating, pricing model, vendor and verification status, linked to
    the canonical Marketplace landing page.
    """

    name = "jetbrains"
    description = (
        "Search JetBrains IDE plugins on the Marketplace, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "plugins"]

    @staticmethod
    def _sort_key(item: dict[str, Any]) -> tuple[int, str]:
        """Return the ordering key for one search hit.

        Higher-download plugins first (canonical plugins outrank obscure
        forks); stable tie-break by plugin name.
        """
        return (-_as_int(item.get("downloads")), _clean(item.get("name")))

    @staticmethod
    def _published_date(item: dict[str, Any]) -> str | None:
        """Extract a YYYY-MM-DD date from the millisecond epoch *cdate*."""
        cdate = item.get("cdate")
        if isinstance(cdate, bool) or not isinstance(cdate, (int, float)) or not cdate:
            return None
        try:
            return datetime.fromtimestamp(int(cdate) / 1000, tz=UTC).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a Marketplace search response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        plugins = data.get("plugins")
        if not isinstance(plugins, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in sorted(
            (entry for entry in plugins if isinstance(entry, dict)),
            key=self._sort_key,
        )[:max_results]:
            name = _clean(item.get("name"))
            if not name:
                continue

            plugin_link = _clean(item.get("link"))
            url = f"{_CANONICAL_URL}{plugin_link}" if plugin_link else _CANONICAL_URL
            preview = _clean(item.get("preview"))
            downloads = _as_int(item.get("downloads"))
            rating = item.get("rating")
            rating_value = (
                round(float(rating), 2)
                if isinstance(rating, (int, float)) and not isinstance(rating, bool)
                else None
            )
            pricing = _clean(item.get("pricingModel")) or "FREE"
            vendor = item.get("vendor")
            vendor_name = ""
            vendor_verified = False
            if isinstance(vendor, dict):
                vendor_name = _clean(vendor.get("name"))
                vendor_verified = bool(vendor.get("isVerified"))
            plugin_tags = [
                _clean(tag) for tag in (item.get("tags") or []) if isinstance(tag, str)
            ]

            snippet_parts: list[str] = []
            if preview:
                snippet_parts.append(preview)
            if downloads:
                snippet_parts.append(f"Downloads: {downloads:,}")
            if rating_value is not None:
                snippet_parts.append(f"Rating: {rating_value}/5")
            snippet_parts.append(f"Pricing: {pricing}")
            if vendor_name:
                vendor_label = (
                    f"Vendor: {vendor_name} (verified)"
                    if vendor_verified
                    else f"Vendor: {vendor_name}"
                )
                snippet_parts.append(vendor_label)
            if not snippet_parts:
                snippet_parts.append("JetBrains IDE plugin")

            results.append(
                SearchResult(
                    title=name,
                    url=url,
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source=_MARKETPLACE_SOURCE,
                    published_date=self._published_date(item),
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "plugin_name": name,
                        "preview": preview,
                        "downloads": downloads,
                        "rating": rating_value,
                        "pricing_model": pricing,
                        "vendor": vendor_name,
                        "vendor_verified": vendor_verified,
                        "tags": plugin_tags,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the JetBrains Marketplace for plugins matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _API_SEARCH_URL,
                params={"search": query, "max": limit},
            )
            resp.raise_for_status()
            data = resp.json()
        return self._parse(data, limit=limit)
