"""Packagist PHP package search via the official keyless search API.

Packagist is the main package repository for PHP (the default registry
used by Composer).  Its public search API requires no API key:

``GET https://packagist.org/search.json?q=QUERY&per_page=N``

The endpoint reports ``total`` plus rich metadata per package: the
vendor/name, description, per-package page URL, repository URL, total
downloads, favers (GitHub-style stars), and an ``abandoned`` flag when a
package is no longer maintained.  Packagist complements the existing
registry providers (npm, PyPI, RubyGems, crates.io, Maven Central,
MetaCPAN, NuGet) which cover the JS, Python, Ruby, Rust, Java, Perl, and
.NET ecosystems but not PHP/Composer.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://packagist.org/search.json"
# The search API caps a single listing request at this many packages.
_MAX_API_RESULTS = 20


class PackagistProvider(BaseProvider):
    """Search PHP/Composer packages published on Packagist.

    Keyless.  Uses the official ``search.json`` endpoint, which covers the
    whole Packagist catalog including Composer plugins, Symfony/Laravel
    bundles, and general PHP libraries.  Each hit carries the vendor/name,
    latest description, downloads, favers, repository link, and a landing
    page on packagist.org.
    """

    name = "packagist"
    description = (
        "Search PHP/Composer packages published on Packagist, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "packages"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace/control characters in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _abandoned_reason(item: dict[str, Any]) -> str:
        """Return the replacement/reason text for an abandoned package."""
        abandoned = item.get("abandoned")
        if abandoned is True:
            return "abandoned"
        if isinstance(abandoned, str):
            reason = PackagistProvider._clean(abandoned)
            return f"abandoned (replacement: {reason})"
        return ""

    def _parse(self, data: dict[str, Any], limit: int | None = None) -> ProviderResult:
        """Parse a Packagist search response into structured results."""
        results: list[SearchResult] = []
        items = data.get("results") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for pkg in items:
            if len(results) >= max_results:
                break
            if not isinstance(pkg, dict):
                continue
            name = self._clean(pkg.get("name"))
            if not name:
                continue

            description = self._clean(pkg.get("description"))
            downloads = pkg.get("downloads") or 0
            favers = pkg.get("favers") or 0
            url = (
                self._clean(pkg.get("url")) or f"https://packagist.org/packages/{name}"
            )

            snippet_parts: list[str] = [description]
            if downloads:
                snippet_parts.append(f"Downloads: {downloads:,}")
            if favers:
                snippet_parts.append(f"Favers: {favers:,}")

            results.append(
                SearchResult(
                    title=name,
                    url=url,
                    snippet=" | ".join(p for p in snippet_parts if p)[
                        :MAX_SNIPPET_LENGTH
                    ],
                    source="packagist.org",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "package_name": name,
                        "repository": self._clean(pkg.get("repository")),
                        "downloads": downloads,
                        "favers": favers,
                        "abandoned_reason": self._abandoned_reason(pkg),
                        "total_hits": data.get("total") or 0,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Packagist for PHP packages matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        qp = {"q": query, "per_page": str(limit)}
        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
