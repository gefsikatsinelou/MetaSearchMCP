"""NuGet (.NET) package search via the official keyless search API.

NuGet is the package manager for the .NET ecosystem and the default
registry for C#, F#, and VB.NET libraries. Its official read-only
search service requires no API key:

``GET https://azuresearch-usnc.nuget.org/query?q=QUERY&take=N``

The search endpoint reports ``totalHits`` plus rich metadata per
package: the id, latest stable version, title, description, authors,
tags, total download count, a project URL, and a ``verified`` flag for
publisher-verified packages. NuGet complements the existing registry
providers (npm, PyPI, RubyGems, crates.io, Maven Central, MetaCPAN)
which cover the JS, Python, Ruby, Rust, Java, and Perl ecosystems but
not .NET.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://azuresearch-usnc.nuget.org/query"
# The search API caps a single listing request at this many packages.
_MAX_API_RESULTS = 20


class NuGetProvider(BaseProvider):
    """Search .NET packages published on NuGet.org.

    Keyless. Uses the official v3 search query endpoint, which covers
    the whole NuGet catalog including packages from nuget.org, the .NET
    team, and community publishers. Each hit carries the id, latest
    stable version, description, authors, tags, total downloads, and a
    landing-page link, plus a ``verified`` flag when the publisher owns
    the id on nuget.org.
    """

    name = "nuget"
    description = "Search .NET/C# packages published on NuGet.org, no API key required."
    tags: ClassVar[list[str]] = ["web", "code", "developer", "packages"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace/control characters in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    def _parse(self, data: dict[str, Any], limit: int | None = None) -> ProviderResult:
        """Parse a NuGet search response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for pkg in data.get("data") or []:
            if len(results) >= max_results:
                break
            if not isinstance(pkg, dict):
                continue
            package_id = self._clean(pkg.get("id"))
            if not package_id:
                continue

            version = self._clean(pkg.get("version"))
            description = self._clean(pkg.get("description"))
            title = self._clean(pkg.get("title")) or package_id
            downloads = pkg.get("totalDownloads") or 0
            authors = [a for a in (pkg.get("authors") or []) if self._clean(a)]
            tags = [t for t in (pkg.get("tags") or []) if self._clean(t)]
            url = (
                pkg.get("projectUrl") or f"https://www.nuget.org/packages/{package_id}/"
            )

            snippet_parts: list[str] = [description]
            if version:
                snippet_parts.append(f"v{version}")
            if downloads:
                snippet_parts.append(f"Downloads: {downloads:,}")

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(p for p in snippet_parts if p)[
                        :MAX_SNIPPET_LENGTH
                    ],
                    source="nuget.org",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "package_id": package_id,
                        "version": version,
                        "authors": authors,
                        "tags": tags,
                        "total_downloads": downloads,
                        "verified": bool(pkg.get("verified")),
                        "total_hits": data.get("totalHits") or 0,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search NuGet.org for .NET packages matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        qp = {"q": query, "take": str(limit), "prerelease": "false"}
        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
