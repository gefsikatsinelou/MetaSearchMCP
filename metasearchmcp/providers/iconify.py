"""Search the Iconify icon catalogue via its public, keyless HTTP API.

Iconify (iconify.design) unifies well over 200,000 open-source vector icons from
150+ icon sets — Material Symbols, Material Design Icons, Tabler, Phosphor,
Bootstrap Icons, Font Awesome, Lucide, ... — behind a single keyword index.
Every icon keeps the licence of the set it comes from, and each one can be
requested as SVG, so an icon found here can be embedded straight into a UI.

The search endpoint is public and keyless::

    GET https://api.iconify.design/search?query=QUERY&limit=N

The response carries the matching icon identifiers as ``prefix:name`` strings
in ``icons``, the number of matches in ``total``, and a ``collections`` mapping
that describes every set contributing a hit: its display name, icon count,
author, licence, category, tags and whether it ships palette (multicolour)
icons.

This complements the image providers (Openverse, Unsplash, Wikimedia Commons,
Met Museum, ...): instead of photographs it answers which vector icon exists
for a concept, which icon set it belongs to, and under which licence it may be
reused.  No API key is required.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.iconify.design/search"
# Public icon browser page of a single icon, keyed by ``prefix/name``.
_ICON_PAGE_URL = "https://icon-sets.iconify.design/"
# Raw SVG rendering of a single icon, keyed by ``prefix/name``.
_SVG_URL = "https://api.iconify.design/"
# Search hits the API is asked for at most; it caps a single response below it.
_MAX_API_RESULTS = 999
# Icon-set tags listed in a snippet.
_SNIPPET_TAG_LIMIT = 3


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _string(value: object) -> str:
    """Return a plain string field, or an empty string."""
    return value if isinstance(value, str) else ""


class IconifyProvider(BaseProvider):
    """Search the Iconify catalogue for open-source vector icons.

    Keyless.  Queries the Iconify search API in a single request and returns
    one hit per matching icon, carrying the icon identifier, the icon set it
    comes from (name, author, licence, category, tags), the set's icon count,
    the SVG URL and the icon's page in the public Iconify browser.
    """

    name = "iconify"
    description = (
        "Search Iconify — 200,000+ open-source vector icons from 150+ icon sets "
        "(Material Symbols, Material Design Icons, Tabler, Phosphor, Font "
        "Awesome, Lucide, ...) — by keyword, returning each icon's set, author, "
        "licence, SVG URL and browser page. No API key required."
    )
    tags: ClassVar[list[str]] = ["web", "media", "image", "design"]

    @staticmethod
    def _icon_query(query: str) -> str:
        """Return the whitespace-normalized keywords of *query*."""
        return " ".join(query.split())

    @staticmethod
    def _split(identifier: str) -> tuple[str, str]:
        """Split an icon identifier such as ``mdi:home`` into prefix and name.

        Identifiers are the catalogue's native ``prefix:name`` form; anything
        that does not carry both halves is reported as empty and skipped.
        """
        prefix, _, name = identifier.partition(":")
        return prefix.strip(), name.strip()

    @staticmethod
    def _collection(collections: dict[str, Any], prefix: str) -> dict[str, Any]:
        """Return the metadata of an icon set, if the response carries it."""
        collection = collections.get(prefix)
        return collection if isinstance(collection, dict) else {}

    @staticmethod
    def _author(collection: dict[str, Any]) -> tuple[str, str]:
        """Return the icon set's author name and homepage."""
        author = collection.get("author")
        if not isinstance(author, dict):
            return "", ""
        return _clean(author.get("name")), _string(author.get("url"))

    @staticmethod
    def _license(collection: dict[str, Any]) -> tuple[str, str, str]:
        """Return the icon set's licence title, SPDX id and URL."""
        license_info = collection.get("license")
        if not isinstance(license_info, dict):
            return "", "", ""
        return (
            _clean(license_info.get("title")),
            _clean(license_info.get("spdx")),
            _string(license_info.get("url")),
        )

    @staticmethod
    def _set_tags(collection: dict[str, Any]) -> list[str]:
        """Return the icon set's descriptive tags, in order and deduplicated."""
        raw = collection.get("tags")
        if not isinstance(raw, list):
            return []
        tags: list[str] = []
        for tag in raw:
            label = _clean(tag)
            if label and label not in tags:
                tags.append(label)
        return tags

    @staticmethod
    def _int(value: object) -> int | None:
        """Return an integer field, ignoring booleans and non-numeric values."""
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value

    @staticmethod
    def _set_name(collection: dict[str, Any], prefix: str) -> str:
        """Return the display name of an icon set, falling back to its prefix."""
        return _clean(collection.get("name")) or prefix

    @classmethod
    def _snippet(
        cls,
        set_name: str,
        prefix: str,
        author: str,
        license_name: str,
        category: str,
        palette: bool,
        svg_url: str,
    ) -> str:
        """Compose the snippet for a single icon."""
        parts = [f"Set: {set_name} ({prefix})"]
        if author:
            parts.append(f"Author: {author}")
        if license_name:
            parts.append(f"License: {license_name}")
        if category:
            parts.append(f"Category: {category}")
        parts.append(f"Palette: {'yes' if palette else 'no'}")
        parts.append(f"SVG: {svg_url}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        identifier: str,
        collections: dict[str, Any],
        total: int | None,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from an Iconify icon identifier."""
        prefix, name = self._split(identifier)
        if not prefix or not name:
            return None

        collection = self._collection(collections, prefix)
        set_name = self._set_name(collection, prefix)
        author, author_url = self._author(collection)
        license_name, license_spdx, license_url = self._license(collection)
        set_tags = self._set_tags(collection)
        category = _clean(collection.get("category"))
        raw_palette = collection.get("palette")
        palette = raw_palette if isinstance(raw_palette, bool) else False
        page_url = f"{_ICON_PAGE_URL}{prefix}/{name}/"
        svg_url = f"{_SVG_URL}{prefix}/{name}.svg"
        set_total = self._int(collection.get("total"))

        return SearchResult(
            title=f"{prefix}:{name}",
            url=page_url,
            snippet=self._snippet(
                set_name,
                prefix,
                author,
                license_name,
                category,
                palette,
                svg_url,
            ),
            source="iconify.design",
            rank=rank,
            provider=self.name,
            extra={
                "identifier": f"{prefix}:{name}",
                "prefix": prefix,
                "name": name,
                "collection": set_name,
                "collection_url": author_url or None,
                "author": author or None,
                "license": license_name or None,
                "license_spdx": license_spdx or None,
                "license_url": license_url or None,
                "category": category or None,
                "collection_tags": set_tags[:_SNIPPET_TAG_LIMIT],
                "palette": palette,
                "height": self._int(collection.get("height")),
                "collection_size": set_total or None,
                "svg_url": svg_url,
                "page_url": page_url,
                "total_results": total,
            },
        )

    def _parse(self, data: object, limit: int) -> ProviderResult:
        """Parse an Iconify search response into structured results."""
        if not isinstance(data, dict):
            return ProviderResult(results=[])

        icons = data.get("icons")
        if not isinstance(icons, list):
            return ProviderResult(results=[])

        raw_collections = data.get("collections")
        collections = raw_collections if isinstance(raw_collections, dict) else {}
        total = self._int(data.get("total"))

        results: list[SearchResult] = []
        seen: set[str] = set()
        for entry in icons:
            if len(results) >= limit:
                break
            if not isinstance(entry, str):
                continue
            built = self._build_result(entry, collections, total, len(results) + 1)
            if built is None:
                continue
            identifier = built.extra["identifier"]
            if identifier in seen:
                continue
            seen.add(identifier)
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Iconify for icons matching *query*.

        A blank query performs no request.  The catalogue's own keyword
        relevance order is preserved in the returned results.
        """
        cleaned = self._icon_query(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={"query": cleaned, "limit": limit},
            )
            resp.raise_for_status()
            data: object = resp.json()

        return self._parse(data, limit)
