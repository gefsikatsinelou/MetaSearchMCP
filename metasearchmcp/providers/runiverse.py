"""Search R packages across CRAN and r-universe via the keyless r-universe API.

r-universe (r-universe.dev) is rOpenSci's package-universe platform: it mirrors
CRAN, Bioconductor and thousands of personal/organisation package repositories
("universes") behind one keyword index that requires no API key::

    GET https://r-universe.dev/api/search?q=QUERY&limit=N

Each hit carries the package name, title, description, maintainer, the universe
(owner) it is published in, its GitHub star count, how many packages depend on
it (``_usedby``), topics, and the last-update timestamp.  Every package also has
a canonical page at ``https://OWNER.r-universe.dev/PACKAGE``, so a result points
straight at installable documentation.

This complements the existing registry providers (npm, PyPI, RubyGems,
crates.io, NuGet, Packagist, Hex, pub.dev, Hackage, Anaconda, AUR, Chocolatey,
Terraform) which cover the JavaScript, Python, Ruby, Rust, .NET, PHP, Elixir,
Dart, Haskell, conda, Arch, Windows, and Terraform ecosystems — but not the
R/statistics ecosystem used across data science, biostatistics and academia.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://r-universe.dev/api/search"
# Fallback package browser when a hit carries no universe (owner) name.
_SEARCH_PAGE_URL = "https://r-universe.dev/search/"
# The search API accepts up to this many hits per request.
_MAX_API_RESULTS = 100
# Free-text fields are clipped before being stitched into a snippet.
_DESCRIPTION_LIMIT = 200
# Topics listed in a snippet.
_SNIPPET_TOPIC_LIMIT = 4


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _string(value: object) -> str:
    """Return a plain string field, or an empty string."""
    return value if isinstance(value, str) else ""


def _count(value: object) -> int | None:
    """Return a non-negative integer counter, ignoring booleans and junk."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    count = int(value)
    return count if count >= 0 else None


def _iso_date(value: object) -> str | None:
    """Convert a Unix timestamp into a ``YYYY-MM-DD`` date, if possible."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=UTC).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


class RUniverseProvider(BaseProvider):
    """Search R packages published on CRAN and r-universe.

    Keyless. Queries the r-universe search index in a single request and
    returns one hit per package, carrying the package name, title,
    description, maintainer, universe, stars, reverse-dependency count,
    topics, last-update date, and the canonical package page.
    """

    name = "runiverse"
    description = (
        "Search R packages across CRAN and r-universe (data science, statistics, "
        "bioconductor, ...), no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "packages"]

    @staticmethod
    def _query(query: str) -> str:
        """Return the whitespace-normalized keywords of *query*."""
        return " ".join(query.split())

    @staticmethod
    def _maintainer(item: dict[str, Any]) -> tuple[str, str]:
        """Return the package maintainer's display name and login handle."""
        maintainer = item.get("maintainer")
        if not isinstance(maintainer, dict):
            return "", ""
        return _clean(maintainer.get("name")), _clean(maintainer.get("login"))

    @staticmethod
    def _topics(item: dict[str, Any]) -> list[str]:
        """Return the package's topic labels, in order and deduplicated."""
        raw = item.get("topics")
        if not isinstance(raw, list):
            return []
        topics: list[str] = []
        for topic in raw:
            label = _clean(topic)
            if label and label not in topics:
                topics.append(label)
        return topics

    @staticmethod
    def _page_url(owner: str, package: str) -> str:
        """Return the canonical r-universe page of a package."""
        if owner:
            return f"https://{owner}.r-universe.dev/{package}"
        return f"{_SEARCH_PAGE_URL}?q={package}"

    @classmethod
    def _snippet(
        cls,
        package_title: str,
        description: str,
        maintainer: str,
        owner: str,
        stars: int | None,
        used_by: int | None,
        topics: list[str],
    ) -> str:
        """Compose the snippet for a single package."""
        parts: list[str] = []
        if description:
            parts.append(description[:_DESCRIPTION_LIMIT])
        elif package_title:
            parts.append(package_title)
        if maintainer:
            parts.append(f"Maintainer: {maintainer}")
        if owner:
            parts.append(f"Universe: {owner}")
        if stars:
            parts.append(f"Stars: {stars:,}")
        if used_by:
            parts.append(f"Used by: {used_by:,}")
        if topics:
            parts.append(f"Topics: {', '.join(topics[:_SNIPPET_TOPIC_LIMIT])}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        total: int | None,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from an r-universe hit."""
        package = _clean(item.get("Package"))
        if not package:
            return None

        package_title = _clean(item.get("Title"))
        description = _clean(item.get("Description"))
        owner = _clean(item.get("_user"))
        maintainer, maintainer_login = self._maintainer(item)
        topics = self._topics(item)
        stars = _count(item.get("stars"))
        used_by = _count(item.get("_usedby"))
        updated = _iso_date(item.get("updated"))
        url = self._page_url(owner, package)

        return SearchResult(
            title=package,
            url=url,
            snippet=self._snippet(
                package_title,
                description,
                maintainer,
                owner,
                stars,
                used_by,
                topics,
            ),
            source="r-universe.dev",
            rank=rank,
            provider=self.name,
            published_date=updated,
            extra={
                "package_name": package,
                "title": package_title,
                "description": description,
                "universe": owner or None,
                "maintainer": maintainer or None,
                "maintainer_login": maintainer_login or None,
                "stars": stars,
                "used_by": used_by,
                "topics": topics,
                "updated": updated,
                "page_url": url,
                "cran_url": (
                    f"https://cran.r-project.org/package={package}"
                    if owner == "cran"
                    else None
                ),
                "total_results": total,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse an r-universe search response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        items = data.get("results")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        total = _count(data.get("total"))
        max_results = limit or self._max_results
        for item in items:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            built = self._build_result(item, total, len(results) + 1)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search CRAN and r-universe for R packages matching *query*.

        A blank query performs no request.  The index's own relevance order is
        preserved in the returned results.
        """
        cleaned = self._query(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={"q": cleaned, "limit": limit},
            )
            resp.raise_for_status()
            data: object = resp.json()

        return self._parse(data, limit=limit)
