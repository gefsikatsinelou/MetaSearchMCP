"""GNOME Shell extension search via the official keyless extensions.gnome.org API.

The GNOME Extensions website hosts shell extensions (applets, dash/panel
tweaks, clipboard managers, window tiling helpers, ...) for the GNOME
desktop.  Its read-only search endpoint requires no key:

``GET https://extensions.gnome.org/extension-query/?search=QUERY&page=1``

The endpoint returns extension records carrying the extension name, uuid,
author/creator, plain-text description, canonical landing-page link, total
download count, and the ``shell_version_map`` describing which GNOME Shell
versions each extension supports.  Because the endpoint's own relevance
ordering is unreliable (e.g. searching ``dash to dock`` can surface
unrelated low-download hits before the canonical Dash to Dock), hits are
re-ranked by download count so the most-used extension for a query appears
first — mirroring the WordPress.org registry providers.

GNOME Extensions complements the existing registry/plugin providers (AMO,
JetBrains Marketplace, Open VSX, Flathub, WordPress.org, ...) by covering
the GNOME desktop-extension ecosystem.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_SEARCH_URL = "https://extensions.gnome.org/extension-query/"
# Canonical site root used to absolutize relative links/icons.
_SITE_BASE = "https://extensions.gnome.org"
# The extension-query endpoint returns at most this many hits per page.
_MAX_API_RESULTS = 10
_EXTENSION_SOURCE = "extensions.gnome.org"


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


def _absolute(path: object) -> str:
    """Return *path* as an absolute extensions.gnome.org URL, or ''.

    The API returns site-relative paths such as
    ``/extension-data/screenshots/screenshot_1177.png``; absolute http(s)
    URLs are returned unchanged.
    """
    cleaned = _clean(path)
    if not cleaned or cleaned.startswith(("http://", "https://")):
        return cleaned
    return f"{_SITE_BASE}{cleaned}"


def _shell_key(shell_version: object) -> tuple[int, int]:
    """Return a sortable (major, minor) key for a GNOME Shell version string.

    Shell versions look like ``3.36``, ``40`` or ``45.beta``; lexicographic
    comparison is wrong across widths (``9`` > ``47``), so each leading
    numeric component is parsed. Unparseable chunks count as 0.
    """
    parts: list[int] = []
    for chunk in str(shell_version).split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        try:
            parts.append(int(digits))
        except ValueError:
            parts.append(0)
        if len(parts) == 2:
            break
    while len(parts) < 2:
        parts.append(0)
    return parts[0], parts[1]


def _shell_range(value: object) -> str:
    """Return a compact ``low-high`` GNOME Shell compatibility range, or ''.

    *value* is the ``shell_version_map`` dict of an extension hit; the range
    spans the numerically lowest to highest supported shell version, e.g.
    ``3.36-47``, or a single version when only one is supported.
    """
    if not isinstance(value, dict):
        return ""
    versions = sorted(
        (key for key in value if isinstance(key, str) and key),
        key=_shell_key,
    )
    if not versions:
        return ""
    low, high = versions[0], versions[-1]
    if low == high:
        return low
    return f"{low}-{high}"


def _sort_key(item: dict[str, Any]) -> tuple[int, str]:
    """Return the ordering key for one raw extension record.

    Higher-download extensions first (the canonical extension for a query
    usually has far more downloads than its forks); uuid breaks ties
    deterministically.
    """
    return (-_as_int(item.get("downloads")), _clean(item.get("uuid")))


def _parse_item(item: dict[str, Any]) -> SearchResult | None:
    """Build a SearchResult from one raw extension record, or None to skip.

    Records without a name or without any usable landing-page URL are
    skipped.
    """
    title = _clean(item.get("name"))
    if not title:
        return None
    link = _clean(item.get("link"))
    extension_id = _as_int(item.get("pk"))
    if link.startswith("/"):
        url = f"{_SITE_BASE}{link}"
    elif link.startswith(("http://", "https://")):
        url = link
    elif extension_id:
        # No link field; the numeric-id URL redirects to the extension page.
        url = f"{_SITE_BASE}/extension/{extension_id}/"
    else:
        return None

    author = _clean(item.get("creator"))
    description = _clean(item.get("description"))
    downloads = _as_int(item.get("downloads"))
    shell_range = _shell_range(item.get("shell_version_map"))

    snippet_parts: list[str] = []
    if description:
        snippet_parts.append(description[:200])
    if downloads:
        snippet_parts.append(f"Downloads: {downloads:,}")
    if shell_range:
        snippet_parts.append(f"GNOME Shell {shell_range}")
    if author:
        snippet_parts.append(f"Author: {author}")
    if not snippet_parts:
        snippet_parts.append("GNOME Shell extension")

    return SearchResult(
        title=title,
        url=url,
        snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
        source=_EXTENSION_SOURCE,
        rank=1,
        provider="gnome_extensions",
        extra={
            "uuid": _clean(item.get("uuid")),
            "extension_id": extension_id,
            "author": author,
            "downloads": downloads,
            "shell_versions": shell_range,
            "homepage": _clean(item.get("url")),
            "screenshot_url": _absolute(item.get("screenshot")),
        },
    )


def _parse(data: object, limit: int | None = None) -> ProviderResult:
    """Parse an extension-query response into structured results."""
    results: list[SearchResult] = []
    if not isinstance(data, dict):
        return ProviderResult(results=results)
    extensions = data.get("extensions")
    if not isinstance(extensions, list):
        return ProviderResult(results=results)

    max_results = limit or _MAX_API_RESULTS
    for item in sorted(
        (entry for entry in extensions if isinstance(entry, dict)),
        key=_sort_key,
    )[:max_results]:
        parsed = _parse_item(item)
        if parsed is None:
            continue
        parsed.rank = len(results) + 1
        results.append(parsed)

    return ProviderResult(results=results)


class GnomeExtensionsProvider(BaseProvider):
    """Search GNOME Shell extensions on extensions.gnome.org.

    Keyless. Uses the official ``extension-query`` JSON endpoint covering
    the whole directory.  Hits are re-ranked by download count so the
    most-used extension for a query appears first.  Each hit carries the
    extension name, uuid, author, downloads, supported GNOME Shell range,
    homepage and screenshot, linked to the canonical landing page.
    """

    name = "gnome_extensions"
    description = (
        "Search GNOME Shell extensions on extensions.gnome.org, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "plugins"]

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse an extension-query response into structured results."""
        return _parse(data, limit=limit)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the GNOME extension directory for extensions matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _API_SEARCH_URL, params={"search": query, "page": 1}
            )
            resp.raise_for_status()
            data = resp.json()
        return self._parse(data, limit=limit)
