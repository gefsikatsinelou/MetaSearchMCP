"""Firefox/Android add-on search via the official keyless Mozilla Add-ons API.

The Mozilla Add-ons (AMO) store hosts browser extensions, themes, and
language packs for Firefox (desktop + Android).  Its read-only search
endpoint requires no key:

``GET https://addons.mozilla.org/api/v5/addons/search/?q=QUERY&lang=en-US&page_size=N&type=extension``

The endpoint returns add-on records carrying the add-on id/slug, localized
name and summary, current version, authors, categories, tags, ratings,
user/download popularity (average_daily_users, weekly_downloads), icon and
screenshots.  Each hit links to the canonical
``addons.mozilla.org/firefox/addon/SLUG`` landing page.  Hits are ordered
by AMO's relevance ranking, which already surfaces the canonical add-on
for a query (e.g. ``ublock`` -> uBlock Origin) first.

AMO complements the existing registry/plugin providers (Open VSX, JetBrains
Marketplace, Flathub, Steam, ...) by covering the browser-extension
ecosystem.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_SEARCH_URL = "https://addons.mozilla.org/api/v5/addons/search/"
# The API caps page size at this value.
_MAX_API_RESULTS = 50
_ADDON_SOURCE = "addons.mozilla.org"
# Only public, non-experimental browser extensions are meaningful hits.
_TYPE_EXTENSION = "extension"
_ACCEPTED_STATUSES = {"public", "nominated"}


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _localized(field: object, fallback: str = "") -> str:
    """Return the plain-text value of an AMO localized dict or string field.

    AMO returns localized fields such as ``name``/``summary`` as dicts keyed
    by locale tag (e.g. ``{"en-US": "uBlock Origin", "de": "..."}``); the
    API is asked for ``lang=en-US`` so that locale is preferred, with any
    other value used as a fallback.
    """
    if not field:
        return fallback
    if isinstance(field, dict):
        for preferred in ("en-US", "en", "en_US"):
            value = field.get(preferred)
            if isinstance(value, str) and value:
                return _clean(value)
        for value in field.values():
            if isinstance(value, str) and value:
                return _clean(value)
        return fallback
    return _clean(field) or fallback


def _as_int(value: object) -> int:
    """Return *value* as an int, or 0 for missing/boolean/non-numeric input."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _iso_date(value: object) -> str | None:
    """Return the YYYY-MM-DD prefix of an ISO-format *value*, if present."""
    if not isinstance(value, str) or not value:
        return None
    prefix = value[:10]
    return prefix or None


class AmoProvider(BaseProvider):
    """Search browser extensions on the Mozilla Add-ons store.

    Keyless. Uses the official ``/api/v5/addons/search/`` endpoint covering
    public Firefox/Android add-ons (extensions, themes, dictionaries; the
    search defaults to extensions). Hits keep AMO's relevance ordering, and
    each hit carries the localized name/summary, current version, authors,
    categories, tags, ratings, average daily users, weekly downloads and
    icons, linked to the canonical AMO landing page.
    """

    name = "amo"
    description = (
        "Search Firefox browser extensions on addons.mozilla.org, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "plugins"]

    @staticmethod
    def _version_of(item: dict[str, Any]) -> str:
        """Return the current-version string of an add-on hit, if any."""
        current_version = item.get("current_version")
        if isinstance(current_version, dict):
            version = current_version.get("version")
            if isinstance(version, str) and version:
                return _clean(version)
        return ""

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse an AMO search response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        items = data.get("results")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in items[:max_results]:
            if not isinstance(item, dict):
                continue
            if item.get("type") not in (None, _TYPE_EXTENSION):
                continue
            if item.get("status") not in (None, *_ACCEPTED_STATUSES):
                continue
            if bool(item.get("is_experimental")):
                continue

            title = _localized(item.get("name"))
            slug = _clean(item.get("slug"))
            if not title and not slug:
                continue
            # A missing localized name is unexpected; fall back to the slug.
            title = title or slug

            summary = _localized(item.get("summary"))
            description = _localized(item.get("description"))
            version = self._version_of(item)
            average_daily_users = _as_int(item.get("average_daily_users"))
            weekly_downloads = _as_int(item.get("weekly_downloads"))

            ratings_data = item.get("ratings")
            rating_value: float | None = None
            rating_count = 0
            if isinstance(ratings_data, dict):
                average = ratings_data.get("average")
                if isinstance(average, (int, float)) and not isinstance(average, bool):
                    rating_value = round(float(average), 2)
                rating_count = _as_int(ratings_data.get("count"))

            authors = [
                _clean(author.get("name"))
                for author in (item.get("authors") or [])
                if isinstance(author, dict)
            ]
            categories = [
                _clean(category)
                for category in (item.get("categories") or [])
                if isinstance(category, str)
            ]

            snippet_parts: list[str] = []
            if summary:
                snippet_parts.append(summary)
            elif description:
                snippet_parts.append(description)
            if version:
                snippet_parts.append(f"v{version}")
            if average_daily_users:
                snippet_parts.append(f"Users: {average_daily_users:,}")
            if weekly_downloads:
                snippet_parts.append(f"Weekly downloads: {weekly_downloads:,}")
            if rating_value is not None:
                snippet_parts.append(f"Rating: {rating_value}/5 ({rating_count})")
            if authors:
                snippet_parts.append(f"Author: {', '.join(authors)}")
            if not snippet_parts:
                snippet_parts.append("Firefox browser extension")

            canonical = (
                f"https://addons.mozilla.org/firefox/addon/{slug}/"
                if slug
                else "https://addons.mozilla.org"
            )
            results.append(
                SearchResult(
                    title=title,
                    url=canonical,
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source=_ADDON_SOURCE,
                    published_date=_iso_date(item.get("last_updated")),
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "addon_id": _as_int(item.get("id")),
                        "slug": slug,
                        "guid": _clean(item.get("guid")),
                        "summary": summary,
                        "description": description,
                        "version": version,
                        "authors": authors,
                        "categories": categories,
                        "tags": [
                            _clean(tag)
                            for tag in (item.get("tags") or [])
                            if isinstance(tag, str)
                        ],
                        "average_daily_users": average_daily_users,
                        "weekly_downloads": weekly_downloads,
                        "rating": rating_value,
                        "rating_count": rating_count,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the Mozilla Add-ons store for extensions matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        request_params = {
            "q": query,
            "lang": "en-US",
            "page_size": limit,
            "type": _TYPE_EXTENSION,
            # No adult-oriented/themes noise; keep results deterministic.
            "sort": "relevance",
        }
        async with self._client() as client:
            resp = await client.get(_API_SEARCH_URL, params=request_params)
            resp.raise_for_status()
            data = resp.json()
        return self._parse(data, limit=limit)
