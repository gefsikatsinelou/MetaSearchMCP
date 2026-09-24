"""Search Debian source packages via the keyless sources.debian.org API.

``sources.debian.org`` is Debian's browsable archive of the *source* packages
that make up the distribution — the packaging trees from which the binary
packages in every suite (``stable``, ``testing``, ``unstable``/``sid``,
backports, ...) are built.  Its read-only REST API requires no key and offers a
name search plus a per-package version history::

    GET https://sources.debian.org/api/search/<query>/
    GET https://sources.debian.org/api/src/<package>/

The search response is ``{"query": ..., "results": {"exact": {...},
"other": [{"name": ...}, ...]}, "suite": ""}``: ``exact`` holds the package
whose name equals the query, ``other`` the alphabetically ordered names that
merely contain it.  The detail response lists every recorded version of a
package with its archive ``area`` and the ``suites`` it currently belongs to,
newest first.

Because the search endpoint only returns names, the first few hits are enriched
with their version/suite history in a second round of (concurrent, failure
tolerant) detail requests.  Each hit links to the package's source page at
``sources.debian.org/src/NAME/``.

This complements the existing registry providers — AUR (Arch), Chocolatey
(Windows), MacPorts (macOS/Darwin), Flathub and Snapcraft (Linux applications),
npm, PyPI, ... — with Debian, the package ecosystem the project did not cover
yet.  No API key is required.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar
from urllib.parse import quote

import httpx

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://sources.debian.org/api/search/{query}/"
_DETAIL_URL = "https://sources.debian.org/api/src/{name}/"
# Canonical human-readable source package page.
_PACKAGE_URL = "https://sources.debian.org/src/{name}/"
_SOURCE = "sources.debian.org"
# The search endpoint returns names only, so the top hits are enriched with
# their version history; beyond this many results no detail request is made.
_MAX_DETAIL_LOOKUPS = 10
# Versions quoted in the snippet before the list is cut short.
_MAX_SNIPPET_VERSIONS = 3
# Snippet of a hit whose version history could not be retrieved.
_FALLBACK_SNIPPET = "Debian source package"


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _str_list(value: object) -> list[str]:
    """Return the non-empty cleaned strings of a JSON list field."""
    if not isinstance(value, (list, tuple)):
        return []
    return [text for entry in value if (text := _clean(entry))]


def _fallback_term(query: str) -> str:
    """Return the longest word of a multi-word query, or an empty string.

    Debian's search matches single package names, so a phrase such as
    ``web framework`` finds nothing; the longest word (usually the specific
    one) is retried as a second, narrower search.
    """
    tokens = query.split()
    if len(tokens) < 2:
        return ""
    return max(tokens, key=len)


def _parse_names(data: object) -> list[str]:
    """Extract the ordered, deduplicated package names of a search response.

    The exact match comes first, followed by the API's own alphabetical order
    of partial matches.  Any other payload shape yields an empty list.
    """
    if not isinstance(data, dict):
        return []
    results = data.get("results")
    if not isinstance(results, dict):
        return []

    names: list[str] = []
    exact = results.get("exact")
    if isinstance(exact, dict):
        name = _clean(exact.get("name"))
        if name:
            names.append(name)

    other = results.get("other")
    if isinstance(other, (list, tuple)):
        for entry in other:
            if not isinstance(entry, dict):
                continue
            name = _clean(entry.get("name"))
            if name and name not in names:
                names.append(name)

    return names


def _parse_versions(data: object) -> list[dict[str, Any]]:
    """Extract the version history of a source package detail response.

    Every entry keeps the upstream Debian version, its archive area and the
    suites that still carry it.  The API's order (newest first) is preserved.
    """
    if not isinstance(data, dict):
        return []
    versions = data.get("versions")
    if not isinstance(versions, (list, tuple)):
        return []

    parsed: list[dict[str, Any]] = []
    for entry in versions:
        if not isinstance(entry, dict):
            continue
        version = _clean(entry.get("version"))
        if not version:
            continue
        parsed.append(
            {
                "version": version,
                "area": _clean(entry.get("area")) or None,
                "suites": _str_list(entry.get("suites")),
            }
        )

    return parsed


def _snippet(versions: list[dict[str, Any]]) -> str:
    """Compose the snippet from a package's version history.

    The newest versions come first; a version that is no longer carried by any
    suite is marked as such.  A package without a retrieved history falls back
    to a static label so that a snippet is never empty.
    """
    if not versions:
        return _FALLBACK_SNIPPET

    parts: list[str] = []
    for entry in versions[:_MAX_SNIPPET_VERSIONS]:
        suites = entry["suites"]
        if suites:
            parts.append(f"{entry['version']} in {', '.join(suites)}")
        else:
            parts.append(f"{entry['version']} (no current suite)")
    return " | ".join(parts)[:MAX_SNIPPET_LENGTH]


class DebianProvider(BaseProvider):
    """Search Debian source packages and their version history.

    Keyless.  *query* is matched against source package names (``curl`` →
    ``curl``, ``curlftpfs``, ``pycurl``, ...).  The first few hits are enriched
    with their version history — the newest version per archive area and the
    Debian suites that currently ship it — and link to the package's page on
    sources.debian.org.
    """

    name = "debian"
    description = (
        "Search Debian source packages via sources.debian.org: package name, "
        "version history per suite (stable, testing, sid, backports) and "
        "archive area. No API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "packages"]

    def _build_result(
        self,
        name: str,
        term: str,
        versions: list[dict[str, Any]] | None,
        total: int,
        rank: int,
    ) -> SearchResult:
        """Build one :class:`SearchResult` from a source package name."""
        history = versions or []
        latest = history[0] if history else None

        return SearchResult(
            title=name,
            url=_PACKAGE_URL.format(name=quote(name, safe="")),
            snippet=_snippet(history),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            extra={
                "name": name,
                "searched_term": term,
                "exact_match": name.lower() == term.lower(),
                "latest_version": latest["version"] if latest else None,
                "suites": latest["suites"] if latest else [],
                "areas": sorted({v["area"] for v in history if v["area"]}),
                "versions": history,
                "total_results": total,
            },
        )

    async def _search_names(self, client: httpx.AsyncClient, term: str) -> list[str]:
        """Run one name search and return the matching package names."""
        resp = await client.get(_SEARCH_URL.format(query=quote(term, safe="")))
        resp.raise_for_status()
        return _parse_names(resp.json())

    async def _lookup(
        self,
        client: httpx.AsyncClient,
        name: str,
    ) -> list[dict[str, Any]]:
        """Fetch the version history of a single source package."""
        resp = await client.get(_DETAIL_URL.format(name=quote(name, safe="")))
        resp.raise_for_status()
        return _parse_versions(resp.json())

    async def _lookups(
        self,
        client: httpx.AsyncClient,
        names: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch the version histories of *names*, tolerating failures.

        All detail requests run concurrently; a package whose lookup fails is
        simply returned without a version history instead of failing the whole
        search.
        """
        if not names:
            return {}

        outcomes = await asyncio.gather(
            *(self._lookup(client, name) for name in names),
            return_exceptions=True,
        )
        details: dict[str, list[dict[str, Any]]] = {}
        for name, outcome in zip(names, outcomes, strict=True):
            if isinstance(outcome, list):
                details[name] = outcome
        return details

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Debian source packages whose name matches *query*.

        A blank query performs no request.  When a multi-word query matches no
        package name, the longest word is retried once.  The returned hits are
        enriched with version history for the top hits only.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results)
        if limit <= 0:
            return ProviderResult(results=[])

        async with self._client() as client:
            term = cleaned
            names = await self._search_names(client, term)
            if not names:
                fallback = _fallback_term(cleaned)
                if fallback:
                    term = fallback
                    names = await self._search_names(client, term)

            total = len(names)
            selected = names[:limit]
            details = await self._lookups(
                client,
                selected[:_MAX_DETAIL_LOOKUPS],
            )

        results = [
            self._build_result(name, term, details.get(name), total, rank)
            for rank, name in enumerate(selected, start=1)
        ]
        return ProviderResult(results=results)
