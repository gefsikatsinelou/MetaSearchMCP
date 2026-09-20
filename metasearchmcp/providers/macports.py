"""MacPorts package search via the official keyless ports API.

MacPorts is the long-running package manager for macOS (and other Darwin
systems), hosting more than fifty thousand ports — command line tools,
libraries, language runtimes, TeX packages and full desktop applications such
as ``git``, ``python312``, ``texlive`` or ``inkscape``.  Its read-only REST API
requires no key and supports keyword search over port names::

    GET https://ports.macports.org/api/v1/ports/
        ?search=<query>&per_page=N&page=1

Each record carries the port name, its directory in the ports tree, the current
version, license, supported platforms, the categories it belongs to, its
maintainers (with GitHub handles and how many ports they own), the available
build variants, the declared build/lib dependencies, whether the port is still
active and, when a port was removed, the port that replaced it.  Hits link to
the canonical ``ports.macports.org/port/NAME/`` page.

This complements the existing registry providers — Chocolatey (Windows), AUR
(Arch), Flathub and Snapcraft (Linux), Docker Hub (containers), npm, PyPI, ... —
with the package ecosystem of macOS that none of them cover.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_ENDPOINT = "https://ports.macports.org/api/v1/ports/"
_SOURCE = "ports.macports.org"
# Canonical human-readable page of a single port.
_PORT_URL = "https://ports.macports.org/port/{name}/"
# The API accepts large page sizes but never serves more than this per request.
_MAX_API_RESULTS = 100
# Longest description quoted in a snippet.
_MAX_SNIPPET_DESCRIPTION = 200
# Number of categories / maintainers listed in a snippet.
_MAX_SNIPPET_LIST = 3


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


def _str_list(value: object) -> list[str]:
    """Return the non-empty cleaned strings of a JSON list field."""
    if not isinstance(value, (list, tuple)):
        return []
    return [text for entry in value if (text := _clean(entry))]


def _truncate(value: str, limit: int) -> str:
    """Shorten *value* to *limit* characters, appending an ellipsis."""
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _maintainers(value: object) -> list[str]:
    """Return the display names of a port's maintainers.

    Maintainers are objects (``{"name": ..., "github": ..., "ports_count": ...}``)
    and can also be plain strings in older payloads; both shapes are accepted.
    """
    if not isinstance(value, (list, tuple)):
        return []
    names: list[str] = []
    for entry in value:
        if isinstance(entry, dict):
            name = _clean(entry.get("name")) or _clean(entry.get("github"))
        else:
            name = _clean(entry)
        if name:
            names.append(name)
    return names


def _dependency_count(value: object) -> int:
    """Count the dependency ports declared across all dependency types."""
    if not isinstance(value, (list, tuple)):
        return 0
    total = 0
    for entry in value:
        if isinstance(entry, dict):
            ports = entry.get("ports")
            if isinstance(ports, (list, tuple)):
                total += len(ports)
    return total


class MacPortsProvider(BaseProvider):
    """Search MacPorts ports available for macOS and other Darwin systems.

    Keyless.  *query* is matched against port names, so hits are the ports whose
    name contains the query term (``git`` → ``git``, ``git-lfs``, ``p5.34-git``,
    ...).  Each result carries the version, license, categories, maintainers,
    build variants and dependency count of the port.
    """

    name = "macports"
    description = (
        "Search the MacPorts package registry for macOS/Darwin: ports with "
        "version, license, platforms, categories, maintainers, build variants "
        "and dependencies. No API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "packages"]

    def _snippet(
        self,
        description: str,
        portdir: str,
        version: str,
        license_text: str,
        categories: list[str],
        maintainers: list[str],
        replaced_by: str,
    ) -> str:
        """Compose the snippet for a single port.

        The description comes first, followed by the version, license,
        categories and maintainers so that a hit stays informative without
        reading ``extra``.  A port without any of those fields falls back to its
        directory in the ports tree so that a snippet is never empty.
        """
        parts: list[str] = []
        if description:
            parts.append(_truncate(description, _MAX_SNIPPET_DESCRIPTION))
        if version:
            parts.append(f"v{version}")
        if license_text:
            parts.append(license_text)
        if categories:
            parts.append(", ".join(categories[:_MAX_SNIPPET_LIST]))
        if maintainers:
            shown = ", ".join(maintainers[:_MAX_SNIPPET_LIST])
            if len(maintainers) > _MAX_SNIPPET_LIST:
                shown += " et al."
            parts.append(f"by {shown}")
        if replaced_by:
            parts.append(f"replaced by {replaced_by}")
        if not parts and portdir:
            parts.append(portdir)
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        total: int | None,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a MacPorts port record."""
        name = _clean(item.get("name"))
        if not name:
            return None

        portdir = _clean(item.get("portdir"))
        version = _clean(item.get("version"))
        license_text = _clean(item.get("license"))
        platforms = _clean(item.get("platforms"))
        homepage = _clean(item.get("homepage"))
        description = _clean(item.get("description"))
        long_description = _clean(item.get("long_description"))
        replaced_by = _clean(item.get("replaced_by"))
        categories = _str_list(item.get("categories"))
        maintainers = _maintainers(item.get("maintainers"))
        variants = _str_list(item.get("variants"))
        active = item.get("active")

        return SearchResult(
            title=name,
            url=_PORT_URL.format(name=name),
            snippet=self._snippet(
                description,
                portdir,
                version,
                license_text,
                categories,
                maintainers,
                replaced_by,
            ),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            extra={
                "name": name,
                "portdir": portdir or None,
                "version": version or None,
                "license": license_text or None,
                "platforms": platforms or None,
                "epoch": _int(item.get("epoch")),
                "categories": categories,
                "maintainers": maintainers,
                "variants": variants,
                "dependency_count": _dependency_count(item.get("dependencies")),
                "active": active if isinstance(active, bool) else None,
                "replaced_by": replaced_by or None,
                "homepage": homepage or None,
                "description": description or None,
                "long_description": long_description or None,
                "total_results": total,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a MacPorts search response into structured results.

        The API's own relevance order is preserved and duplicate port names are
        collapsed onto their first occurrence.  Any other payload shape yields an
        empty result set.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        entries = data.get("results")
        if not isinstance(entries, list):
            return ProviderResult(results=results)

        total = _int(data.get("count"))
        max_results = self._max_results if limit is None else limit
        seen: set[str] = set()
        for item in entries:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            name = _clean(item.get("name"))
            if name and name in seen:
                continue
            built = self._build_result(item, total, len(results) + 1)
            if built is None:
                continue
            if name:
                seen.add(name)
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search MacPorts for ports whose name matches *query*.

        A blank query performs no request (an empty search would return the
        whole registry).  A single page is fetched, sized to ``num_results``.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        if limit <= 0:
            return ProviderResult(results=[])

        async with self._client() as client:
            resp = await client.get(
                _ENDPOINT,
                params={
                    "search": cleaned,
                    "per_page": limit,
                    "page": 1,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit)
