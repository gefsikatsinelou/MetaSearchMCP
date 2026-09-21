"""Modrinth Minecraft mod, plugin and content search via the keyless API.

Modrinth (modrinth.com) is the largest open catalogue of Minecraft community
content and exposes a documented, keyless search endpoint:

``GET https://api.modrinth.com/v2/search?query=QUERY&limit=N``

A bare query performs a relevance-ranked full-text match across project names,
summaries and metadata.  Every hit carries the project title and slug, its
summary, the author/organisation behind it, the community categories and mod
loaders it targets, the Minecraft versions it supports, download and follower
counts, its licence, the client/server side requirement, and creation or update
timestamps.

The catalogue covers mods, plugins, modpacks, shaders, resource packs and
datapacks.  This complements the existing games providers (Steam store search,
Scryfall card search and CheapShark price drops) with the Minecraft
community-content ecosystem none of them index.

The API asks callers to identify themselves with a descriptive ``User-Agent``;
the shared provider client already sends one.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote_plus

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.modrinth.com/v2/search"
_SITE_URL = "https://modrinth.com"
_SOURCE = "modrinth.com"
# The API caps a single request at 100 hits; keep well below that.
_MAX_API_RESULTS = 100
# Longest project summary quoted in a snippet.
_MAX_SNIPPET_DESCRIPTION = 220
# Number of supported Minecraft versions kept in ``extra``.
_MAX_GAME_VERSIONS = 20
# Fallback search page used when a hit carries no slug.
_SEARCH_URL = f"{_SITE_URL}/search?q={{query}}"

# Slugs that name a mod loader or server platform rather than a content
# category, so they can be reported separately from the categories.
_LOADERS = frozenset(
    {
        "bukkit",
        "bungeecord",
        "canvas",
        "datapack",
        "fabric",
        "folia",
        "forge",
        "iris",
        "liteloader",
        "minecraft",
        "modloader",
        "neoforge",
        "optifine",
        "paper",
        "purpur",
        "quilt",
        "rift",
        "spigot",
        "sponge",
        "velocity",
        "waterfall",
    }
)

# Readable labels for the project types the catalogue indexes.
_PROJECT_TYPE_LABELS = {
    "datapack": "Datapack",
    "mod": "Mod",
    "modpack": "Modpack",
    "plugin": "Plugin",
    "resourcepack": "Resource pack",
    "shader": "Shader",
}


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _text_list(value: object, limit: int | None = None) -> list[str]:
    """Return the unique non-empty strings of a JSON list field.

    *limit* keeps at most that many entries, counting from the start of the
    list; the remaining entries are dropped.
    """
    if not isinstance(value, (list, tuple)):
        return []
    items: list[str] = []
    for entry in value:
        text = _clean(entry)
        if text and text not in items:
            items.append(text)
            if limit is not None and len(items) >= limit:
                break
    return items


def _int(value: object) -> int | None:
    """Return an integer field, ignoring booleans and non-integer values."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _truncate(value: str, limit: int) -> str:
    """Shorten *value* to *limit* characters, appending an ellipsis."""
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


class ModrinthProvider(BaseProvider):
    """Search Modrinth for Minecraft mods, plugins and other content.

    Keyless.  *query* is matched against project names, summaries and
    metadata, and results come back in the API's relevance order.  Each result
    carries the summary, author, categories, mod loaders, supported Minecraft
    versions, download/follower counts and licence of a project.
    """

    name = "modrinth"
    description = (
        "Search Modrinth for Minecraft mods, plugins, modpacks, shaders, "
        "resource packs and datapacks: summary, author, categories and mod "
        "loaders, supported Minecraft versions, download/follower counts, "
        "licence and client/server side support. No API key required."
    )
    tags: ClassVar[list[str]] = ["web", "media", "games", "mods"]

    @staticmethod
    def _project_url(hit: dict[str, Any]) -> str:
        """Build a link to the project page of a search hit.

        Modrinth project URLs are ``/{project_type}/{slug}``.  Hits without a
        slug fall back to a site search for the project title so a link is
        always returned.
        """
        slug = _clean(hit.get("slug"))
        if not slug:
            return _SEARCH_URL.format(query=quote_plus(_clean(hit.get("title"))))
        project_type = _clean(hit.get("project_type")) or "mod"
        return f"{_SITE_URL}/{project_type}/{slug}"

    @staticmethod
    def _categories(hit: dict[str, Any]) -> tuple[list[str], list[str]]:
        """Split a hit's category slugs into (categories, loaders).

        The API mixes content categories with mod loaders in a single
        ``categories`` list; the loaders are pulled out so callers can filter
        on either.
        """
        categories = hit.get("display_categories") or hit.get("categories")
        slugs = _text_list(categories)
        loaders = [slug for slug in slugs if slug.lower() in _LOADERS]
        content = [slug for slug in slugs if slug.lower() not in _LOADERS]
        return content, loaders

    @staticmethod
    def _snippet(
        description: str,
        project_type: str,
        loaders: list[str],
        versions: list[str],
        downloads: int | None,
        follows: int | None,
        license_name: str,
    ) -> str:
        """Compose the snippet for a single Modrinth project.

        The summary comes first, followed by a metadata tail of project type,
        loaders, newest supported Minecraft version, popularity and licence.
        """
        parts: list[str] = []
        if description:
            parts.append(_truncate(description, _MAX_SNIPPET_DESCRIPTION))

        details: list[str] = []
        label = _PROJECT_TYPE_LABELS.get(project_type, project_type.capitalize())
        if label:
            details.append(label)
        if loaders:
            details.append(", ".join(loaders))
        if versions:
            details.append(f"MC {versions[-1]}")
        if downloads is not None:
            details.append(f"{downloads:,} downloads")
        if follows is not None:
            details.append(f"{follows:,} followers")
        if license_name:
            details.append(license_name)
        if details:
            parts.append(" | ".join(details))

        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        hit: dict[str, Any],
        rank: int,
        total: int | None,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a Modrinth search hit."""
        title = _clean(hit.get("title"))
        if not title:
            return None

        description = _clean(hit.get("description"))
        project_type = _clean(hit.get("project_type"))
        author = _clean(hit.get("author"))
        organization = _clean(hit.get("organization"))
        license_name = _clean(hit.get("license"))
        categories, loaders = self._categories(hit)
        versions = _text_list(hit.get("versions"), _MAX_GAME_VERSIONS)
        downloads = _int(hit.get("downloads"))
        follows = _int(hit.get("follows"))
        created = _clean(hit.get("date_created"))
        modified = _clean(hit.get("date_modified"))

        return SearchResult(
            title=title,
            url=self._project_url(hit),
            snippet=self._snippet(
                description,
                project_type,
                loaders,
                versions,
                downloads,
                follows,
                license_name,
            ),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            published_date=self._iso_date_prefix(created),
            extra={
                "project_id": _clean(hit.get("project_id")),
                "slug": _clean(hit.get("slug")),
                "project_type": project_type,
                "author": author or None,
                "organization": organization or None,
                "categories": categories,
                "loaders": loaders,
                "game_versions": versions,
                "downloads": downloads,
                "follows": follows,
                "license": license_name or None,
                "client_side": _clean(hit.get("client_side")) or None,
                "server_side": _clean(hit.get("server_side")) or None,
                "latest_version": _clean(hit.get("latest_version")) or None,
                "icon_url": _clean(hit.get("icon_url")) or None,
                "date_modified": modified or None,
                "total_results": total,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a Modrinth search response into structured results.

        The API's relevance order is preserved and duplicate project ids are
        collapsed onto their first occurrence.  Any other payload shape yields
        an empty result set.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        hits = data.get("hits")
        if not isinstance(hits, list):
            return ProviderResult(results=results)

        max_results = self._max_results if limit is None else limit
        total = _int(data.get("total_hits"))
        seen: set[str] = set()
        for hit in hits:
            if len(results) >= max_results:
                break
            if not isinstance(hit, dict):
                continue
            key = _clean(hit.get("project_id")) or _clean(hit.get("slug"))
            if key and key in seen:
                continue
            built = self._build_result(hit, len(results) + 1, total)
            if built is None:
                continue
            if key:
                seen.add(key)
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Modrinth for Minecraft content matching *query*.

        A blank query performs no request.  The API answers an unsatisfiable
        search with an empty ``hits`` list and reports malformed requests with
        HTTP 400, which is treated as "no results" here.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        if limit <= 0:
            return ProviderResult(results=[])

        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={"query": cleaned, "limit": str(limit)},
            )
            if resp.status_code in (400, 404):
                return ProviderResult(results=[])
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
