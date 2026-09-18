"""Search the Wallhaven wallpaper collection.

Wallhaven is a community wallpaper site whose public JSON API supports keyword
search without an API key::

    GET https://wallhaven.cc/api/v1/search
        ?q=<query>&categories=111&purity=100
        &sorting=relevance&order=desc&page=1

The keyword is matched against wallpaper tags, titles, usernames and other
metadata, and Wallhaven's own relevance ranking is preserved.  A single
request returns up to ``per_page`` (24) wallpapers plus the total number of
matches and the last page number in the ``meta`` block, so — like the Flickr,
Openverse and Unsplash providers — results are paginated by the caller rather
than by this provider.

Each record carries the wallpaper UUID, canonical page and short URL, the
full-size image URL and thumbnails, the resolution, aspect ratio, file size
and type, the category (``general``, ``anime`` or ``people``), purity
(``sfw``, ``sketchy`` or ``nsfw``), dominant colours, view/favourite counts
and the creation timestamp.  Wallhaven does not give wallpapers a title, so
the resolution and category are used to build a readable one.

``safe_search`` maps onto the API's ``purity`` filter: a safe search asks for
``sfw`` wallpapers only, while an unrestricted search also includes
``sketchy`` and ``nsfw`` entries.  Adult entries require a Wallhaven API key
upstream, so unauthenticated unrestricted searches still return only the
publicly listed wallpapers.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_ENDPOINT = "https://wallhaven.cc/api/v1/search"
_SOURCE = "wallhaven.cc"
# Canonical page of a wallpaper, keyed by its Wallhaven id.
_WALLPAPER_URL = "https://wallhaven.cc/w/"
# Wallhaven caps ``per_page`` at 24 records for unauthenticated requests.
_MAX_API_RESULTS = 24
# Category bit mask: general (1) + anime (2) + people (4).
_ALL_CATEGORIES = "111"
# Purity bit mask: sfw (1) + sketchy (2) + nsfw (4).  The restricted mask
# keeps adult wallpapers out; the unrestricted mask relies on Wallhaven to
# drop anything the caller may not see.
_SAFE_PURITY = "100"
_UNRESTRICTED_PURITY = "111"
# Number of dominant colour codes listed in a snippet.
_MAX_SNIPPET_COLORS = 5
_BYTES_PER_KB = 1024
_BYTES_PER_MB = _BYTES_PER_KB * 1024


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _int(value: object) -> int | None:
    """Return an integer field, ignoring booleans and non-integer values."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _strings(value: object) -> list[str]:
    """Return the non-empty string entries of a list-valued field."""
    if not isinstance(value, (list, tuple)):
        return []
    return [text for entry in value if (text := _clean(entry))]


def _label(value: object) -> str:
    """Render a Wallhaven enum field (``sfw``, ``anime``) for display."""
    cleaned = _clean(value)
    if cleaned.lower() == "nsfw":
        return "NSFW"
    return cleaned.replace("_", " ").title()


def _resolution(item: dict[str, Any]) -> str:
    """Return a wallpaper's resolution, building it from its dimensions."""
    resolution = _clean(item.get("resolution"))
    if resolution:
        return resolution
    width = _int(item.get("dimension_x"))
    height = _int(item.get("dimension_y"))
    if width is None or height is None:
        return ""
    return f"{width}x{height}"


def _human_size(value: object) -> str:
    """Render a byte count such as ``1.2 MB`` or ``285 KB``."""
    size = _int(value)
    if size is None or size < 0:
        return ""
    if size >= _BYTES_PER_MB:
        return f"{size / _BYTES_PER_MB:.1f} MB"
    if size >= _BYTES_PER_KB:
        return f"{size / _BYTES_PER_KB:.0f} KB"
    return f"{size} B"


def _thumbs(value: object) -> dict[str, str]:
    """Return the non-empty thumbnail URLs keyed by size."""
    if not isinstance(value, dict):
        return {}
    return {
        size: text
        for size, raw in value.items()
        if isinstance(size, str) and (text := _clean(raw))
    }


class WallhavenProvider(BaseProvider):
    """Search wallpapers in the Wallhaven collection.

    Keyless.  A single request matches *query* against Wallhaven's wallpaper
    metadata and returns hits in relevance order, each carrying its image and
    thumbnail URLs, resolution, file size and type, category, purity, colours
    and view/favourite counts.
    """

    name = "wallhaven"
    description = (
        "Search Wallhaven, the community wallpaper site: high-resolution "
        "desktop wallpapers by keyword, with resolution and aspect ratio, "
        "file size and type, category (general/anime/people), purity, "
        "dominant colours, view/favourite counts, full-size image and "
        "thumbnail URLs. No API key required."
    )
    tags: ClassVar[list[str]] = ["image", "media", "wallpaper"]

    def _title(self, item: dict[str, Any], wallpaper_id: str) -> str:
        """Build a readable title from a wallpaper's resolution and category.

        Wallhaven has no title field, so the resolution and category are
        combined (e.g. ``1920x1080 Anime wallpaper``); a record missing both
        falls back to its identifier.
        """
        parts = [
            part for part in (_resolution(item), _label(item.get("category"))) if part
        ]
        if not parts:
            return f"Wallhaven {wallpaper_id}"
        return " ".join([*parts, "wallpaper"])

    def _snippet(self, item: dict[str, Any]) -> str:
        """Compose the snippet for a single wallpaper record.

        Resolution, file size and type, category, non-safe purity, colours
        and view/favourite counts are combined so that a result stays
        informative even when the caller does not look at ``extra``.
        """
        parts: list[str] = []

        resolution = _resolution(item)
        if resolution:
            parts.append(resolution)

        size = _human_size(item.get("file_size"))
        if size:
            parts.append(size)

        file_type = _clean(item.get("file_type"))
        if file_type:
            parts.append(file_type.rsplit("/", 1)[-1])

        category = _label(item.get("category"))
        if category:
            parts.append(category)

        purity = _clean(item.get("purity"))
        if purity and purity != "sfw":
            parts.append(_label(purity))

        colors = _strings(item.get("colors"))[:_MAX_SNIPPET_COLORS]
        if colors:
            parts.append(" ".join(colors))

        views = _int(item.get("views"))
        if views is not None:
            parts.append(f"{views:,} views")

        favorites = _int(item.get("favorites"))
        if favorites is not None:
            parts.append(f"{favorites:,} favorites")

        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        total: int | None,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a Wallhaven wallpaper record."""
        wallpaper_id = _clean(item.get("id"))
        if not wallpaper_id:
            return None

        thumbs = _thumbs(item.get("thumbs"))
        image_url = _clean(item.get("path"))

        return SearchResult(
            title=self._title(item, wallpaper_id),
            url=_clean(item.get("url")) or f"{_WALLPAPER_URL}{wallpaper_id}",
            snippet=self._snippet(item),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            published_date=self._iso_date_prefix(_clean(item.get("created_at"))),
            extra={
                "wallhaven_id": wallpaper_id,
                "resolution": _resolution(item) or None,
                "width": _int(item.get("dimension_x")),
                "height": _int(item.get("dimension_y")),
                "aspect_ratio": _clean(item.get("ratio")) or None,
                "category": _clean(item.get("category")) or None,
                "purity": _clean(item.get("purity")) or None,
                "file_size": _int(item.get("file_size")),
                "file_size_human": _human_size(item.get("file_size")) or None,
                "file_type": _clean(item.get("file_type")) or None,
                "image_url": image_url or None,
                "thumbnail_url": thumbs.get("original") or thumbs.get("large") or None,
                "short_url": _clean(item.get("short_url")) or None,
                "colors": _strings(item.get("colors")),
                "views": _int(item.get("views")),
                "favorites": _int(item.get("favorites")),
                "source_url": _clean(item.get("source")) or None,
                "total_results": total,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a Wallhaven search response into structured results.

        Wallhaven's own relevance order is preserved; any other payload shape
        yields an empty page.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        items = data.get("data")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        meta = data.get("meta")
        total = _int(meta.get("total")) if isinstance(meta, dict) else None
        max_results = limit or self._max_results
        for item in items:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            built = self._build_result(item, total, len(results) + 1)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Wallhaven wallpapers for *query*.

        A blank query performs no request.  Wallhaven matches the keyword
        against wallpaper metadata and returns hits in its own relevance
        order.  When ``params.safe_search`` is set only ``sfw`` wallpapers are
        requested; otherwise ``sketchy`` and ``nsfw`` entries are included as
        well.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        purity = _SAFE_PURITY if params.safe_search else _UNRESTRICTED_PURITY
        request_params: dict[str, Any] = {
            "q": cleaned,
            "categories": _ALL_CATEGORIES,
            "purity": purity,
            "sorting": "relevance",
            "order": "desc",
            "page": 1,
        }
        async with self._client() as client:
            resp = await client.get(_ENDPOINT, params=request_params)
            resp.raise_for_status()
            data: object = resp.json()

        return self._parse(data, limit)
