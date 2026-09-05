"""Hackage (Haskell) package search via the official keyless API.

Hackage is the central package archive for the Haskell ecosystem (used by
the Cabal toolchain). Its read-only JSON API requires no key:

``GET https://hackage.haskell.org/packages/search.json?terms=QUERY``

The search index returns ranked package names; the provider then fetches
the version list from ``/package/NAME.json``, picks the newest uploaded
release, and pulls its metadata (synopsis, homepage, license, uploader,
and upload date) from ``/package/NAME-VERSION.json``, reusing one HTTP
session. Results link to the canonical ``hackage.haskell.org/package/NAME``
landing page. Hackage complements the existing registry providers (npm,
PyPI, RubyGems, crates.io, Maven Central, MetaCPAN, NuGet, Packagist,
Hex, pub.dev) which cover most other ecosystems but not Haskell/Cabal.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_SEARCH_URL = "https://hackage.haskell.org/packages/search.json"
_API_PACKAGE_URL = "https://hackage.haskell.org/package"
# HTML landing pages live under /package, distinct from the JSON endpoints.
_CANONICAL_URL = "https://hackage.haskell.org/package"


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


class HackageProvider(BaseProvider):
    """Search Haskell/Cabal packages published on Hackage.

    Keyless. Uses the official ``packages/search.json`` index plus
    per-package version/metadata lookups, covering the whole Hackage
    catalog including lens, aeson, and general Haskell libraries. Each hit
    carries the package name, latest version, synopsis, license, homepage,
    uploader, and upload date, linked to the canonical Hackage landing page.
    """

    name = "hackage"
    description = (
        "Search Haskell/Cabal packages published on Hackage, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "packages"]

    @staticmethod
    def _parse_search_hits(data: object) -> list[str]:
        """Return the ordered package names from a search response."""
        if not isinstance(data, list):
            return []
        names: list[str] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            name = _clean(entry.get("name"))
            if name and name not in names:
                names.append(name)
        return names

    def _result_from_meta(
        self, name: str, version: str, data: object, rank: int
    ) -> SearchResult | None:
        """Build a result from a per-package metadata response."""
        if not isinstance(data, dict):
            return None

        synopsis = _clean(data.get("synopsis"))
        license_text = _clean(data.get("license"))
        homepage = _clean(data.get("homepage"))
        version = _clean(data.get("version")) or version
        uploaded = _clean(data.get("uploaded_at"))

        url = homepage or f"{_CANONICAL_URL}/{name}"
        snippet_parts: list[str] = [synopsis]
        if version:
            snippet_parts.append(f"v{version}")
        if license_text:
            snippet_parts.append(f"License: {license_text}")

        return SearchResult(
            title=name,
            url=url,
            snippet=" | ".join(p for p in snippet_parts if p)[:MAX_SNIPPET_LENGTH],
            source="hackage.haskell.org",
            rank=rank,
            provider=self.name,
            published_date=uploaded[:10] or None,
            extra={
                "package_name": name,
                "version": version,
                "license": license_text,
                "homepage": homepage,
                "uploader": _clean(data.get("uploader")),
                "uploaded_at": uploaded,
            },
        )

    @staticmethod
    def _latest_version(data: object) -> str:
        """Return the newest uploaded version from a version-list response."""
        if not isinstance(data, dict):
            return ""

        # Keys look like "1.2.3" (preferred) or "0.1.0.0"; sorting the
        # strings lexicographically is wrong across widths, so compare on
        # the parsed numeric components.
        def key(v: str) -> tuple[int, ...]:
            parts: list[int] = []
            for chunk in v.replace("-", ".").split("."):
                try:
                    parts.append(int(chunk))
                except ValueError:
                    parts.append(0)
            return tuple(parts)

        versions = [v for v in data if key(v)]
        return max(versions, key=key) if versions else ""

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Hackage for Haskell packages matching *query*."""
        limit = min(params.num_results, self._max_results)
        results: list[SearchResult] = []
        async with self._client() as client:
            resp = await client.get(_API_SEARCH_URL, params={"terms": query})
            resp.raise_for_status()
            names = self._parse_search_hits(resp.json())[:limit]

            for name in names:
                if len(results) >= limit:
                    break
                version = await self._fetch_latest_version(client, name)
                meta = await self._fetch_package_meta(client, name, version)
                result = self._result_from_meta(
                    name, version, meta, rank=len(results) + 1
                )
                if result is not None:
                    results.append(result)

        return ProviderResult(results=results)

    async def _fetch_latest_version(self, client: httpx.AsyncClient, name: str) -> str:
        """Return the newest uploaded version for *name* ('' if unknown)."""
        try:
            resp = await client.get(f"{_API_PACKAGE_URL}/{name}.json")
            if resp.status_code != 200:
                return ""
            return self._latest_version(resp.json())
        except (httpx.HTTPError, ValueError):
            return ""

    async def _fetch_package_meta(
        self, client: httpx.AsyncClient, name: str, version: str
    ) -> dict[str, Any] | None:
        """Fetch metadata for one release of *name* from the JSON API."""
        if not version:
            return None
        try:
            resp = await client.get(f"{_API_PACKAGE_URL}/{name}-{version}.json")
            if resp.status_code != 200:
                return None
            data = resp.json()
            return data if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            return None
