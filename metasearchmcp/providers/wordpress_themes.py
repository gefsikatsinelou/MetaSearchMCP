"""WordPress.org theme search via the official keyless Themes API.

The WordPress.org theme directory hosts ~15k free themes for the
WordPress CMS (blogging, business, e-commerce, portfolio, block themes,
...).  Its read-only search endpoint requires no key:

``GET https://api.wordpress.org/themes/info/1.2/?action=query_themes&request[search]=QUERY&request[per_page]=N&request[fields][active_installs]=true&request[fields][downloaded]=true&request[fields][last_updated]=true``

The endpoint returns per-theme records carrying the theme name, slug,
version, author, WordPress compatibility (requires, tested), rating
(0-100) with rating counts, downloads, last-updated date, tags,
screenshot/preview URLs, homepage and download link.  Each hit links to
the canonical ``wordpress.org/themes/SLUG`` landing page.  Because the
API's default ordering is relevance-based and not guaranteed to surface
the canonical theme first, hits are re-ranked by download popularity so
the most-used theme for a query appears first — e.g. searching for
``blog`` surfaces Astra rather than a niche fork.

WordPress.org themes complement the existing registry providers
(JetBrains Marketplace, Open VSX, AMO, Flathub, wordpress_plugins, ...)
by covering the WordPress theme/design ecosystem.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_SEARCH_URL = "https://api.wordpress.org/themes/info/1.2/"
# The API caps per_page at this value.
_MAX_API_RESULTS = 50
_THEME_SOURCE = "wordpress.org"
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _strip_html(value: object) -> str:
    """Return *value* with HTML tags removed and whitespace collapsed."""
    if not value:
        return ""
    if isinstance(value, dict):
        # Theme API returns the author as a dict of user fields.
        value = (
            value.get("display_name")
            or value.get("author")
            or value.get("user_nicename")
        )
    return _clean(_TAG_RE.sub(" ", str(value)))


def _as_int(value: object) -> int:
    """Return *value* as an int, or 0 for missing/boolean/non-numeric input."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _wp_date(value: object) -> str | None:
    """Return a YYYY-MM-DD date from a WordPress.org date string.

    The API returns localized datetime strings such as ``2026-08-31
    1:04pm GMT`` for ``last_updated``; the leading date is extracted and
    anything unparseable yields ``None``.
    """
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d %I:%M%p GMT", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    prefix = text[:10]
    if len(prefix) == 10 and prefix[4] == "-" and prefix[7] == "-":
        return prefix
    return None


def _parse_item(item: dict[str, Any]) -> SearchResult | None:
    """Build a SearchResult from one raw theme record, or None to skip.

    Records with neither a name nor a slug are unusable and skipped.
    """
    title = _clean(item.get("name"))
    slug = _clean(item.get("slug"))
    if not title and not slug:
        return None
    # A missing name is unexpected; fall back to the slug.
    title = title or slug
    if not slug:
        canonical = "https://wordpress.org/themes/"
    else:
        canonical = f"https://wordpress.org/themes/{slug}/"

    author = _strip_html(item.get("author"))
    description = _strip_html(item.get("description"))
    version = _clean(item.get("version"))
    requires = _clean(item.get("requires"))
    tested = _clean(item.get("tested"))
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
    screenshot_url = _clean(item.get("screenshot_url"))

    snippet_parts: list[str] = []
    if description:
        snippet_parts.append(description[:200])
    if version:
        snippet_parts.append(f"v{version}")
    if downloads:
        snippet_parts.append(f"Downloads: {downloads:,}")
    if rating_value is not None and num_ratings:
        snippet_parts.append(f"Rating: {rating_value}/5 ({num_ratings})")
    if requires:
        snippet_parts.append(f"Requires WP: {requires}")
    if tested:
        snippet_parts.append(f"Tested up to: {tested}")
    if author:
        snippet_parts.append(f"Author: {author}")
    if not snippet_parts:
        snippet_parts.append("WordPress theme")

    return SearchResult(
        title=title,
        url=canonical,
        snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
        source=_THEME_SOURCE,
        published_date=_wp_date(item.get("last_updated")),
        rank=1,
        provider="wordpress_themes",
        extra={
            "slug": slug,
            "version": version,
            "author": author,
            "requires_wp": requires,
            "tested_up_to": tested,
            "rating": rating_value,
            "rating_count": num_ratings,
            "total_downloads": downloads,
            "last_updated": _wp_date(item.get("last_updated")),
            "homepage": homepage,
            "tags": tags,
            "screenshot_url": screenshot_url,
            "download_link": download_link,
        },
    )


def _sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    """Return the ordering key for one raw theme record.

    Higher-download themes first (canonical themes outrank obscure
    forks); ratings break download ties; slug gives a stable final
    tie-break.
    """
    return (
        -_as_int(item.get("downloaded")),
        -_as_int(item.get("num_ratings")),
        _clean(item.get("slug")),
    )


def _parse(data: object, limit: int | None = None) -> ProviderResult:
    """Parse a WordPress.org query_themes response into structured results."""
    results: list[SearchResult] = []
    if not isinstance(data, dict):
        return ProviderResult(results=results)
    themes = data.get("themes")
    if not isinstance(themes, list):
        return ProviderResult(results=results)

    max_results = limit or _MAX_API_RESULTS
    for item in sorted(
        (entry for entry in themes if isinstance(entry, dict)),
        key=_sort_key,
    )[:max_results]:
        parsed = _parse_item(item)
        if parsed is None:
            continue
        parsed.rank = len(results) + 1
        results.append(parsed)

    return ProviderResult(results=results)


class WordPressThemesProvider(BaseProvider):
    """Search themes on the WordPress.org theme directory.

    Keyless. Uses the official ``query_themes`` action of the Themes
    Info API covering the whole directory. Hits are re-ranked by
    download popularity so the most popular (canonical) theme for a
    query surfaces first. Each hit carries the name, slug, version,
    author, WordPress compatibility, rating, downloads and update date,
    linked to the canonical WordPress.org landing page.
    """

    name = "wordpress_themes"
    description = "Search themes on the WordPress.org directory, no API key required."
    tags: ClassVar[list[str]] = ["web", "code", "developer", "plugins"]

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a WordPress.org query_themes response into structured results."""
        return _parse(data, limit=limit)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the WordPress.org directory for themes matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        request_params = {
            "action": "query_themes",
            "request[search]": query,
            "request[per_page]": limit,
            "request[page]": 1,
            # The Themes API omits popularity fields unless explicitly asked.
            "request[fields][downloaded]": "true",
            "request[fields][active_installs]": "true",
            "request[fields][num_ratings]": "true",
            "request[fields][rating]": "true",
            "request[fields][last_updated]": "true",
            "request[fields][description]": "true",
            "request[fields][screenshot_url]": "true",
            "request[fields][tags]": "true",
            "request[fields][homepage]": "true",
            "request[fields][download_link]": "true",
        }
        async with self._client() as client:
            resp = await client.get(_API_SEARCH_URL, params=request_params)
            resp.raise_for_status()
            data = resp.json()
        return self._parse(data, limit=limit)
