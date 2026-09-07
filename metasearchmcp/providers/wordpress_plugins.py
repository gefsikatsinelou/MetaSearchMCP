"""WordPress.org plugin search via the official keyless Plugins API.

The WordPress.org plugin directory hosts 60k+ free plugins for the
WordPress CMS (SEO, backups, page builders, security, e-commerce, ...).
Its read-only search endpoint requires no key:

``GET https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request[search]=QUERY&request[per_page]=N``

The endpoint returns per-plugin records carrying the plugin name, slug,
version, author, WordPress/PHP compatibility (requires, tested up to),
rating (0-100) with rating counts, active installs, total downloads,
dates (added, last updated), tags, icons, homepage and download link.
Each hit links to the canonical ``wordpress.org/plugins/SLUG`` landing
page. Because the API's default ordering is relevance-based and not
guaranteed to surface the canonical plugin first, hits are re-ranked by
active-install popularity so the most-used plugin for a query appears
first — e.g. searching for ``backup`` surfaces UpdraftPlus rather than a
niche fork.

WordPress.org plugins complement the existing registry providers
(JetBrains Marketplace, Open VSX, AMO, Flathub, npm, PyPI, ...) by
covering the WordPress/CMS ecosystem.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_SEARCH_URL = "https://api.wordpress.org/plugins/info/1.2/"
# The API caps per_page at this value.
_MAX_API_RESULTS = 50
_PLUGIN_SOURCE = "wordpress.org"
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _strip_html(value: object) -> str:
    """Return *value* with HTML entities decoded and tags removed."""
    if not value:
        return ""
    unescaped = html.unescape(str(value))
    return _clean(_TAG_RE.sub(" ", unescaped))


def _as_int(value: object) -> int:
    """Return *value* as an int, or 0 for missing/boolean/non-numeric input."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _wp_date(value: object) -> str | None:
    """Return a YYYY-MM-DD date from a WordPress.org date string.

    The API mixes plain dates (``added``: ``2018-11-19``) with localized
    datetimes (``last_updated``: ``2026-08-21 8:00am GMT``); both formats
    are accepted and anything unparseable yields ``None``.
    """
    if not isinstance(value, str) or not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %I:%M%p GMT"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_item(item: dict[str, Any]) -> SearchResult | None:
    """Build a SearchResult from one raw plugin record, or None to skip.

    Records with neither a name nor a slug are unusable and skipped.
    """
    title = _strip_html(item.get("name"))
    slug = _clean(item.get("slug"))
    if not title and not slug:
        return None
    # A missing name is unexpected; fall back to the slug.
    title = title or slug
    if not slug:
        canonical = "https://wordpress.org/plugins/"
    else:
        canonical = f"https://wordpress.org/plugins/{slug}/"

    author = _strip_html(item.get("author"))
    short_description = _strip_html(item.get("short_description"))
    version = _clean(item.get("version"))
    requires = _clean(item.get("requires"))
    requires_php = _clean(item.get("requires_php"))
    tested = _clean(item.get("tested"))
    active_installs = _as_int(item.get("active_installs"))
    downloads = _as_int(item.get("downloaded"))
    num_ratings = _as_int(item.get("num_ratings"))
    homepage = _clean(item.get("homepage"))
    download_link = _clean(item.get("download_link"))

    raw_rating = item.get("rating")
    rating_value: float | None = None
    if isinstance(raw_rating, (int, float)) and not isinstance(raw_rating, bool):
        rating_value = round(float(raw_rating) / 20.0, 2)

    tags = [
        _clean(tag) for tag in (item.get("tags") or {}).values() if isinstance(tag, str)
    ]
    icons = item.get("icons")
    icon = ""
    if isinstance(icons, dict):
        icon = _clean(icons.get("2x") or icons.get("1x"))

    snippet_parts: list[str] = []
    if short_description:
        snippet_parts.append(short_description)
    if version:
        snippet_parts.append(f"v{version}")
    if active_installs:
        snippet_parts.append(f"Active installs: {active_installs:,}+")
    if downloads:
        snippet_parts.append(f"Downloads: {downloads:,}")
    if rating_value is not None and num_ratings:
        snippet_parts.append(f"Rating: {rating_value}/5 ({num_ratings})")
    if requires:
        snippet_parts.append(f"Requires WP: {requires}")
    if author:
        snippet_parts.append(f"Author: {author}")
    if not snippet_parts:
        snippet_parts.append("WordPress plugin")

    return SearchResult(
        title=title,
        url=canonical,
        snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
        source=_PLUGIN_SOURCE,
        published_date=_wp_date(item.get("added")),
        rank=1,
        provider="wordpress_plugins",
        extra={
            "slug": slug,
            "version": version,
            "author": author,
            "requires_wp": requires,
            "requires_php": requires_php,
            "tested_up_to": tested,
            "rating": rating_value,
            "rating_count": num_ratings,
            "active_installs": active_installs,
            "total_downloads": downloads,
            "added": _wp_date(item.get("added")),
            "last_updated": _wp_date(item.get("last_updated")),
            "homepage": homepage,
            "tags": tags,
            "icon": icon,
            "download_link": download_link,
        },
    )


def _sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    """Return the ordering key for one raw plugin record.

    Higher-install plugins first (canonical plugins outrank obscure
    forks); downloads break install ties; slug gives a stable final
    tie-break.
    """
    return (
        -_as_int(item.get("active_installs")),
        -_as_int(item.get("downloaded")),
        _clean(item.get("slug")),
    )


def _parse(data: object, limit: int | None = None) -> ProviderResult:
    """Parse a WordPress.org query_plugins response into structured results."""
    results: list[SearchResult] = []
    if not isinstance(data, dict):
        return ProviderResult(results=results)
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        return ProviderResult(results=results)

    max_results = limit or _MAX_API_RESULTS
    for item in sorted(
        (entry for entry in plugins if isinstance(entry, dict)),
        key=_sort_key,
    )[:max_results]:
        parsed = _parse_item(item)
        if parsed is None:
            continue
        parsed.rank = len(results) + 1
        results.append(parsed)

    return ProviderResult(results=results)


class WordPressPluginsProvider(BaseProvider):
    """Search plugins on the WordPress.org plugin directory.

    Keyless. Uses the official ``query_plugins`` action of the Plugins
    Info API covering the whole directory. Hits are re-ranked by active
    installs so the most popular (canonical) plugin for a query surfaces
    first. Each hit carries the name, slug, version, author,
    WordPress/PHP compatibility, rating, active installs, downloads and
    dates, linked to the canonical WordPress.org landing page.
    """

    name = "wordpress_plugins"
    description = "Search plugins on the WordPress.org directory, no API key required."
    tags: ClassVar[list[str]] = ["web", "code", "developer", "plugins"]

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a WordPress.org query_plugins response into structured results."""
        return _parse(data, limit=limit)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the WordPress.org directory for plugins matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        request_params = {
            "action": "query_plugins",
            "request[search]": query,
            "request[per_page]": limit,
            "request[page]": 1,
        }
        async with self._client() as client:
            resp = await client.get(_API_SEARCH_URL, params=request_params)
            resp.raise_for_status()
            data = resp.json()
        return self._parse(data, limit=limit)
