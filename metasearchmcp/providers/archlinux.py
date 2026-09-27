"""Official Arch Linux repository package search via the keyless JSON API.

The official Arch Linux repositories (``core`` and ``extra``) ship the
distribution's maintained binary packages, complementing the community-driven
AUR already covered by the ``aur`` provider. The public search endpoint that
backs the archlinux.org package browser returns JSON and requires no key:

``GET https://archlinux.org/packages/search/json/?q=QUERY``

Two endpoint modes are combined for relevance:

* ``q=`` runs a full-text match over package names *and* descriptions. Its
  results arrive in alphabetical order and are capped at 250 rows, so a broad
  query (e.g. ``python``) can push the canonical ``python`` package out of the
  returned page entirely.
* ``name=`` matches package names exactly, which reliably surfaces the
  canonical package for single-token queries.

The provider issues both lookups, merges the hit lists, and re-ranks by name
closeness (exact > prefix > substring > description-only) so the package the
user most likely wants lands first. Duplicate ``pkgname`` rows across
architectures (``any`` / ``x86_64``) and repos (``extra`` vs
``extra-testing``) are collapsed so every package appears once, preferring the
stable repo and the native ``x86_64`` build. Hits link to the canonical
``archlinux.org/packages/REPO/ARCH/NAME`` page and carry repo, architecture,
version, maintainer, licence, dependency and update metadata.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_SEARCH_URL = "https://archlinux.org/packages/search/json/"
_CANONICAL_URL = "https://archlinux.org/packages"
_MAX_API_RESULTS = 250
_TRUSTED_ARCHES = {"x86_64": 0, "any": 1}


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _string_list(value: object) -> list[str]:
    """Return the cleaned string members of a list-valued API field."""
    if not isinstance(value, list):
        return []
    return [cleaned for item in value if (cleaned := _clean(item))]


def _version_label(item: dict[str, Any]) -> str:
    """Render an Arch package version, including the epoch when present."""
    pkgver = _clean(item.get("pkgver"))
    pkgrel = _clean(item.get("pkgrel"))
    version = f"{pkgver}-{pkgrel}" if pkgrel else pkgver
    epoch = item.get("epoch") or 0
    if isinstance(epoch, int) and not isinstance(epoch, bool) and epoch > 0:
        version = f"{epoch}:{version}"
    return version


class ArchLinuxProvider(BaseProvider):
    """Search official Arch Linux repository packages (core/extra).

    Keyless. Combines the exact-name and full-text search modes of the
    archlinux.org JSON API, ranks the canonical package first, and collapses
    per-architecture duplicates. Each hit carries the package name, version,
    description, repo, architecture, maintainers (or orphaned flag), licences,
    dependencies and update dates.
    """

    name = "archlinux"
    description = (
        "Search official Arch Linux repository packages (core/extra), "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "packages"]

    @staticmethod
    def _items(payload: object) -> list[dict[str, Any]]:
        """Return the package records from one JSON API response."""
        if not isinstance(payload, dict):
            return []
        items = payload.get("results")
        if not isinstance(items, list):
            return []
        return [entry for entry in items if isinstance(entry, dict)]

    @staticmethod
    def _sort_key(item: dict[str, Any], query: str) -> tuple[int, int, int, str]:
        """Return the relevance ordering key for one package record.

        Packages whose name equals the query rank first, then name prefixes,
        name substrings and finally description-only matches. Stable packages
        outrank ``*-testing`` repo rows and native builds outrank foreign
        architectures; the package name breaks remaining ties.
        """
        name = _clean(item.get("pkgname")).lower()
        if name == query:
            rank = 0
        elif name.startswith(query):
            rank = 1
        elif query and query in name:
            rank = 2
        elif query and query in _clean(item.get("pkgdesc")).lower():
            rank = 3
        else:
            rank = 4
        repo = _clean(item.get("repo")).lower()
        testing = 1 if repo.endswith("-testing") else 0
        arch_rank = _TRUSTED_ARCHES.get(_clean(item.get("arch")).lower(), 2)
        return (rank, testing, arch_rank, name)

    def _parse(
        self,
        items: list[dict[str, Any]],
        query: str = "",
        limit: int | None = None,
    ) -> ProviderResult:
        """Rank and convert merged Arch package records into results."""
        normalized_query = _clean(query).lower()
        max_results = limit or self._max_results
        seen: set[str] = set()
        results: list[SearchResult] = []

        ordered = sorted(
            items,
            key=lambda item: self._sort_key(item, normalized_query),
        )
        for item in ordered:
            package_name = _clean(item.get("pkgname"))
            if not package_name or package_name.lower() in seen:
                continue
            seen.add(package_name.lower())
            if len(results) >= max_results:
                break

            repo = _clean(item.get("repo"))
            arch = _clean(item.get("arch"))
            description = _clean(item.get("pkgdesc"))
            version = _version_label(item)
            maintainers = _string_list(item.get("maintainers"))
            licenses = _string_list(item.get("licenses"))
            homepage = _clean(item.get("url"))
            build_date = self._iso_date_prefix(_clean(item.get("build_date")))
            flag_date = self._iso_date_prefix(_clean(item.get("flag_date")))
            url = f"{_CANONICAL_URL}/{repo}/{arch}/{package_name}/"

            snippet_parts: list[str] = []
            if description:
                snippet_parts.append(description)
            if version:
                snippet_parts.append(f"v{version}")
            if repo:
                snippet_parts.append(f"{repo}/{arch}" if arch else repo)
            snippet_parts.append(
                f"Maintainer: {', '.join(maintainers)}" if maintainers else "Orphaned"
            )
            if build_date:
                snippet_parts.append(f"Updated: {build_date}")
            if flag_date:
                snippet_parts.append("Flagged out-of-date")

            results.append(
                SearchResult(
                    title=package_name,
                    url=url,
                    snippet=" | ".join(part for part in snippet_parts if part)[
                        :MAX_SNIPPET_LENGTH
                    ],
                    source="archlinux.org",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=build_date,
                    extra={
                        "package_name": package_name,
                        "version": version,
                        "description": description,
                        "repo": repo,
                        "arch": arch,
                        "maintainer": ", ".join(maintainers),
                        "licenses": licenses,
                        "groups": _string_list(item.get("groups")),
                        "depends": _string_list(item.get("depends")),
                        "provides": _string_list(item.get("provides")),
                        "homepage": homepage,
                        "filename": _clean(item.get("filename")),
                        "compressed_size": item.get("compressed_size"),
                        "installed_size": item.get("installed_size"),
                        "build_date": _clean(item.get("build_date")),
                        "last_update": _clean(item.get("last_update")),
                        "flag_date": _clean(item.get("flag_date")) or None,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search official Arch repositories for packages matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        items: list[dict[str, Any]] = []
        async with self._client() as client:
            lookup = query.strip()
            if lookup and " " not in lookup:
                # Exact-name lookup guarantees the canonical package is
                # returned even when the full-text page is truncated.
                resp = await client.get(
                    _API_SEARCH_URL,
                    params={"name": lookup},
                )
                resp.raise_for_status()
                items.extend(self._items(resp.json()))
            resp = await client.get(
                _API_SEARCH_URL,
                params={"q": query, "limit": _MAX_API_RESULTS},
            )
            resp.raise_for_status()
            items.extend(self._items(resp.json()))
        return self._parse(items, query, limit=limit)
