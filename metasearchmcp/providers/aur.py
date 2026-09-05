"""AUR (Arch Linux User Repository) package search via the official keyless API.

The AUR is the community-driven package repository for Arch Linux and
Arch-based distributions (Manjaro, EndeavourOS, CachyOS, ...). Its read-only
RPC endpoint requires no key:

``GET https://aur.archlinux.org/rpc/?v=5&type=search&arg=QUERY``

The endpoint returns package records carrying the version, description,
number of votes, popularity score, maintainer (or an orphaned flag), and
homepage. Because the default ``by=name`` ordering is alphabetical, the
provider re-ranks hits by vote count (descending) so the canonical package
surfaces first — e.g. searching for ``bat`` yields the real ``bat`` package
rather than ``altayibat-bin``.  Each hit links to the canonical
``aur.archlinux.org/packages/NAME`` landing page. AUR complements the
existing registry providers (npm, PyPI, RubyGems, crates.io, NuGet,
Packagist, Hex, pub.dev, Hackage, Anaconda) which cover language/OS package
managers but not the Arch Linux ecosystem.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_SEARCH_URL = "https://aur.archlinux.org/rpc/"
_CANONICAL_URL = "https://aur.archlinux.org/packages"
_MAX_API_RESULTS = 100


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


class AurProvider(BaseProvider):
    """Search Arch Linux AUR packages (community and orphaned).

    Keyless. Uses the official read-only RPC ``search`` endpoint covering
    the whole AUR catalog. Hits are re-ranked by vote count so the most
    popular (canonical) package for a query surfaces first. Each hit
    carries the package name, version, description, votes, popularity,
    maintainer/orphan status, and homepage, linked to the canonical
    AUR landing page.
    """

    name = "aur"
    description = "Search Arch Linux AUR packages, no API key required."
    tags: ClassVar[list[str]] = ["web", "code", "developer", "packages"]

    @staticmethod
    def _sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
        """Return the ordering key for one search hit.

        Higher-vote packages first (canonical packages outrank obscure
        forks); stable tie-break by package name.
        """
        votes = item.get("NumVotes") or 0
        if isinstance(votes, bool) or not isinstance(votes, int):
            votes = 0
        return (-votes, _clean(item.get("Name")))

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse an AUR RPC search response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        items = data.get("results")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in sorted(
            (entry for entry in items if isinstance(entry, dict)),
            key=self._sort_key,
        )[:max_results]:
            name = _clean(item.get("Name"))
            if not name:
                continue

            version = _clean(item.get("Version"))
            description = _clean(item.get("Description"))
            votes = item.get("NumVotes") or 0
            popularity = item.get("Popularity") or 0.0
            maintainer = _clean(item.get("Maintainer"))
            homepage = _clean(item.get("URL"))
            out_of_date = item.get("OutOfDate")
            if isinstance(out_of_date, (int, float)) and out_of_date:
                out_of_date_value: str | None = str(int(out_of_date))
            else:
                out_of_date_value = None

            url = homepage or f"{_CANONICAL_URL}/{name}"
            snippet_parts: list[str] = []
            if description:
                snippet_parts.append(description)
            if version:
                snippet_parts.append(f"v{version}")
            if votes:
                snippet_parts.append(f"Votes: {int(votes):,}")
            popularity_value = float(popularity)
            if popularity_value >= 0.001:
                snippet_parts.append(f"Popularity: {popularity_value:.3f}")
            snippet_parts.append(
                f"Maintainer: {maintainer}" if maintainer else "Orphaned"
            )

            results.append(
                SearchResult(
                    title=name,
                    url=url,
                    snippet=" | ".join(p for p in snippet_parts if p)[
                        :MAX_SNIPPET_LENGTH
                    ],
                    source="aur.archlinux.org",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "package_name": name,
                        "version": version,
                        "description": description,
                        "votes": int(votes),
                        "popularity": float(popularity),
                        "maintainer": maintainer,
                        "out_of_date": out_of_date_value,
                        "homepage": homepage,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the AUR for packages matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        qp = {"v": 5, "type": "search", "arg": query}
        async with self._client() as client:
            resp = await client.get(_API_SEARCH_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()
        return self._parse(data, limit=limit)
