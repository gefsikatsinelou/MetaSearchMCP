"""Hex.pm package search via the official keyless search API.

Hex is the package manager for the Elixir ecosystem (the default
registry for Elixir and Erlang libraries). Its read-only search API
requires no API key:

``GET https://hex.pm/api/packages?search=QUERY&sort=downloads&page=N``

Each hit carries the package name, latest (stable) version, total
download count, description, license, and a canonical landing-page
link. Hex complements the existing registry providers (npm, PyPI,
RubyGems, crates.io, Maven Central, MetaCPAN, NuGet, Packagist) which
cover the JS, Python, Ruby, Rust, Java, Perl, .NET, and PHP ecosystems
but not Elixir/Erlang.
"""

from __future__ import annotations

from typing import ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://hex.pm/api/packages"
# The API returns up to this many packages per page.
_PAGE_SIZE = 100


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


class HexProvider(BaseProvider):
    """Search Elixir/Erlang packages published on Hex.pm.

    Keyless. Uses the official ``/api/packages`` endpoint, which covers
    the whole Hex.pm catalog including Phoenix, Ecto, and general Elixir
    libraries. Each hit carries the package name, latest stable version,
    description, license, and total download count, plus a landing page
    on hex.pm.
    """

    name = "hex"
    description = (
        "Search Elixir/Erlang packages published on Hex.pm, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "packages"]

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a Hex.pm search response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in data:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            name = _clean(item.get("name"))
            if not name:
                continue

            meta = item.get("meta")
            if not isinstance(meta, dict):
                meta = {}
            description = _clean(meta.get("description"))
            licenses = meta.get("licenses")
            if not isinstance(licenses, list):
                licenses = []
            license_text = ", ".join(_clean(lic) for lic in licenses if _clean(lic))

            downloads = item.get("downloads")
            total_downloads = downloads.get("all") if isinstance(downloads, dict) else 0

            version = _clean(item.get("latest_stable_version")) or _clean(
                item.get("latest_version")
            )
            snippet_parts: list[str] = [description]
            if version:
                snippet_parts.append(f"v{version}")
            if total_downloads:
                snippet_parts.append(f"Downloads: {total_downloads:,}")

            results.append(
                SearchResult(
                    title=name,
                    url=_clean(item.get("html_url"))
                    or f"https://hex.pm/packages/{name}",
                    snippet=" | ".join(p for p in snippet_parts if p)[
                        :MAX_SNIPPET_LENGTH
                    ],
                    source="hex.pm",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "package_name": name,
                        "version": version,
                        "license": license_text,
                        "total_downloads": total_downloads,
                        "updated_at": _clean(item.get("updated_at")),
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Hex.pm for Elixir/Erlang packages matching *query*."""
        limit = min(params.num_results, self._max_results)
        qp = {"search": query, "sort": "downloads"}
        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
