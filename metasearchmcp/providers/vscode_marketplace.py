"""VS Code Marketplace search via the public keyless gallery extensionquery API.

The Visual Studio Code Marketplace hosts 100k+ extensions for VS Code and
other Code-based editors (language servers, themes, debuggers, snippets,
...). Its read-only gallery endpoint accepts ``POST`` requests and needs
no key:

``POST https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery``

The request body carries a JSON filter with the search text
(``filterType 10``); the response returns per-extension records with the
extension name, publisher, short description, latest version, dates, and
usage statistics (total installs, average rating, rating count). Each hit
links to the canonical ``marketplace.visualstudio.com/items?itemName=...``
landing page. Because the gallery's own relevance ordering does not always
surface the canonical extension first, hits are re-ranked by install count
so the most-used extension for a query appears first — mirroring the
WordPress.org and GNOME Extensions registry providers.

VS Code Marketplace complements the existing registry/IDE providers
(Open VSX, JetBrains Marketplace, AMO, Flathub, ...) by covering the
proprietary-but-public Microsoft extension ecosystem.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_SEARCH_URL = (
    "https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery"
)
# The gallery API version used by the marketplace website and VS Code itself.
_API_VERSION = "application/json;api-version=3.0-preview.1"
# Request flags: latest version only + statistics + version properties/files.
_REQUEST_FLAGS = 914
# The gallery API caps page size at this value.
_MAX_API_RESULTS = 50
# Canonical landing page for an extension item.
_ITEM_BASE = "https://marketplace.visualstudio.com/items"
_EXTENSION_SOURCE = "marketplace.visualstudio.com"


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _iso_date(value: object) -> str | None:
    """Return a YYYY-MM-DD date prefix from an ISO-format string, or None."""
    if not isinstance(value, str) or not value:
        return None
    prefix = value[:10]
    if len(prefix) < 10 or prefix[4] != "-" or prefix[7] != "-":
        return None
    return prefix


def _statistic(item: dict[str, Any], name: str) -> float | None:
    """Return the numeric value of a named usage statistic, or None.

    The gallery reports statistics such as ``install``, ``averagerating``
    and ``ratingcount`` as a list of ``{statisticName, value}`` records.
    """
    raw_stats = item.get("statistics")
    if not isinstance(raw_stats, list):
        return None
    for record in raw_stats:
        if not isinstance(record, dict) or record.get("statisticName") != name:
            continue
        raw = record.get("value")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        return float(raw)
    return None


def _install_count(item: dict[str, Any]) -> int:
    """Return the total install count of an extension record, or 0."""
    value = _statistic(item, "install")
    return int(value) if value is not None else 0


def _parse_item(item: dict[str, Any]) -> SearchResult | None:
    """Build a SearchResult from one raw extension record, or None to skip.

    Records missing a display name or the publisher/extension names needed
    to build the canonical item URL are unusable and skipped.
    """
    publisher_raw = item.get("publisher")
    publisher_name = _clean(
        publisher_raw.get("publisherName") if isinstance(publisher_raw, dict) else ""
    )
    publisher_display = (
        publisher_raw.get("displayName") if isinstance(publisher_raw, dict) else ""
    )
    extension = _clean(item.get("extensionName"))
    title = _clean(item.get("displayName")) or extension
    # The canonical item URL needs the real publisher/extension names; a
    # display-only publisher (no publisherName) cannot be linked.
    if not title or not publisher_name or not extension:
        return None
    url = f"{_ITEM_BASE}?itemName={publisher_name}.{extension}"

    versions = item.get("versions")
    version = ""
    if isinstance(versions, list):
        for record in versions:
            if isinstance(record, dict) and _clean(record.get("version")):
                version = _clean(record.get("version"))
                break

    description = _clean(item.get("shortDescription"))
    installs = _install_count(item)
    rating_count_raw = _statistic(item, "ratingcount")
    rating_count = int(rating_count_raw) if rating_count_raw is not None else 0
    rating_raw = _statistic(item, "averagerating")
    rating = round(rating_raw, 2) if rating_raw is not None else None
    published = _iso_date(item.get("publishedDate"))
    last_updated = _iso_date(item.get("lastUpdated"))

    snippet_parts: list[str] = []
    if description:
        snippet_parts.append(description)
    if version:
        snippet_parts.append(f"v{version}")
    if installs:
        snippet_parts.append(f"Installs: {installs:,}")
    if rating is not None and rating_count:
        snippet_parts.append(f"Rating: {rating}/5 ({rating_count})")
    if publisher_display:
        snippet_parts.append(f"Publisher: {publisher_display}")
    elif publisher_name:
        snippet_parts.append(f"Publisher: {publisher_name}")
    if not snippet_parts:
        snippet_parts.append("VS Code extension")

    return SearchResult(
        title=title,
        url=url,
        snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
        source=_EXTENSION_SOURCE,
        published_date=published,
        rank=1,
        provider="vscode_marketplace",
        extra={
            "extension_id": _clean(item.get("extensionId")),
            "extension_name": extension,
            "publisher": publisher_name,
            "version": version,
            "installs": installs,
            "rating": rating,
            "rating_count": rating_count,
            "published_date": published,
            "last_updated": last_updated,
        },
    )


def _sort_key(item: dict[str, Any]) -> tuple[int, str]:
    """Return the ordering key for one raw extension record.

    Higher-install extensions first (the canonical extension for a query
    usually outranks forks by orders of magnitude); the extension name
    breaks ties deterministically.
    """
    return (-_install_count(item), _clean(item.get("extensionName")))


def _parse(data: object, limit: int | None = None) -> ProviderResult:
    """Parse an extensionquery response into structured results."""
    results: list[SearchResult] = []
    if not isinstance(data, dict):
        return ProviderResult(results=results)
    result_groups = data.get("results")
    if not isinstance(result_groups, list):
        return ProviderResult(results=results)

    extensions: list[dict[str, Any]] = []
    for group in result_groups:
        group_extensions = group.get("extensions") if isinstance(group, dict) else None
        if isinstance(group_extensions, list):
            extensions.extend(
                entry for entry in group_extensions if isinstance(entry, dict)
            )

    max_results = limit or _MAX_API_RESULTS
    for item in sorted(extensions, key=_sort_key)[:max_results]:
        parsed = _parse_item(item)
        if parsed is None:
            continue
        parsed.rank = len(results) + 1
        results.append(parsed)

    return ProviderResult(results=results)


class VSCodeMarketplaceProvider(BaseProvider):
    """Search extensions on the Visual Studio Code Marketplace.

    Keyless. Uses the marketplace's public gallery ``extensionquery``
    endpoint covering the whole catalog. Hits are re-ranked by install
    count so the most popular (canonical) extension for a query surfaces
    first. Each hit carries the extension name, publisher, latest version,
    description, installs, rating and dates, linked to the canonical
    marketplace landing page.
    """

    name = "vscode_marketplace"
    description = (
        "Search the Visual Studio Code Marketplace (VS Code extensions), "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "plugins"]

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse an extensionquery response into structured results."""
        return _parse(data, limit=limit)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the marketplace for extensions matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        body: dict[str, Any] = {
            "filters": [
                {
                    "criteria": [{"filterType": 10, "value": query}],
                    "pageNumber": 1,
                    "pageSize": limit,
                },
            ],
            "flags": _REQUEST_FLAGS,
        }
        headers = {"Accept": _API_VERSION}
        async with self._client() as client:
            resp = await client.post(_API_SEARCH_URL, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return self._parse(data, limit=limit)
