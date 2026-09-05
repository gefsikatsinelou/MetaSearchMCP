"""Anaconda (conda package) search via the official keyless search API.

Anaconda.org is the central distribution hub for the conda package
ecosystem, hosting the popular ``conda-forge``, ``defaults``, and
``bioconda`` channels used by Python data-science and scientific
workflows.  Its read-only search API requires no API key:

``GET https://api.anaconda.org/search?name=QUERY``

The endpoint returns per-package records carrying the owner/channel,
full ``owner/name`` id, latest version, summary/description, license,
homepage, and total download count.  Because the raw index groups hits
by package name across many personal channels, the provider boosts
packages hosted on the well-known curated channels (``conda-forge``,
``defaults``, ``bioconda``, ``main``) so they surface first, and the
results link to the canonical ``anaconda.org/OWNER/NAME`` landing page.
Anaconda complements the existing registry providers (npm, PyPI,
RubyGems, crates.io, Maven Central, MetaCPAN, NuGet, Packagist, Hex,
pub.dev, Hackage) which cover most other ecosystems but not the conda
binary-package universe.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_SEARCH_URL = "https://api.anaconda.org/search"
_API_PACKAGE_URL = "https://api.anaconda.org/package"
_CANONICAL_URL = "https://anaconda.org"
# Curated channels whose packages are treated as primary hits.
_PREFERRED_CHANNELS = ("conda-forge", "bioconda", "defaults", "main")
# The search API caps a single listing request at this many records.
_MAX_API_RESULTS = 20


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _channel_rank(channel: str) -> int:
    """Return a sort priority for *channel* (0 = curated, higher = worse)."""
    if channel == "conda-forge":
        return 0
    if channel in ("bioconda", "defaults", "main"):
        return 1
    return 2


class AnacondaProvider(BaseProvider):
    """Search conda packages published on Anaconda.org.

    Keyless. Uses the official ``/search`` endpoint, which covers the
    whole conda catalog including the conda-forge, bioconda, and defaults
    channels. Curated-channel packages are ranked first, so searching for
    a name such as ``numpy`` surfaces ``conda-forge/numpy`` rather than
    stale personal forks. Each hit carries the owner/channel, package
    name, latest version, summary, license, homepage, and total
    download count, linked to the canonical Anaconda.org landing page.
    """

    name = "anaconda"
    description = (
        "Search conda packages published on Anaconda.org, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "packages"]

    @staticmethod
    def _sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
        """Return the ordering key for one search hit.

        Curated channels first; within a channel, higher-download packages
        first; stable tie-break by full name.
        """
        channel = _clean(item.get("owner"))
        return (_channel_rank(channel), -(item.get("ndownloads") or 0), channel)

    def _dedupe_packages(self, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep only the best-ranked hit per package name."""
        by_name: dict[str, dict[str, Any]] = {}
        items = [item for item in data if isinstance(item, dict)]
        for item in sorted(items, key=self._sort_key):
            if not isinstance(item, dict):
                continue
            name = _clean(item.get("name"))
            if not name:
                continue
            by_name.setdefault(name, item)
        return list(by_name.values())

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse an Anaconda search response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in self._dedupe_packages(data)[:max_results]:
            name = _clean(item.get("name"))
            full_name = _clean(item.get("full_name")) or name
            owner = _clean(item.get("owner"))
            channel = owner or "unknown"
            version = _clean(item.get("latest_version"))
            summary = _clean(item.get("summary")) or _clean(item.get("description"))
            license_text = _clean(item.get("license"))
            homepage = _clean(item.get("home"))
            downloads = item.get("ndownloads") or 0
            url = (
                f"{_CANONICAL_URL}/{full_name}"
                if full_name
                else f"{_CANONICAL_URL}/{owner}/{name}"
            )

            snippet_parts: list[str] = [f"[{channel}]"]
            if summary:
                snippet_parts.append(summary)
            if version:
                snippet_parts.append(f"v{version}")
            if downloads:
                snippet_parts.append(f"Downloads: {downloads:,}")

            results.append(
                SearchResult(
                    title=f"{full_name}",
                    url=url,
                    snippet=" | ".join(p for p in snippet_parts if p)[
                        :MAX_SNIPPET_LENGTH
                    ],
                    source="anaconda.org",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "package_name": name,
                        "channel": channel,
                        "full_name": full_name,
                        "version": version,
                        "license": license_text,
                        "homepage": homepage,
                        "downloads": downloads,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def _fetch_package_meta(
        self, client: httpx.AsyncClient, full_name: str
    ) -> dict[str, Any] | None:
        """Fetch metadata for one package from the API (best-effort).

        The search index already carries most fields; this enriches a hit
        with the current latest version when the index omits it.
        """
        try:
            resp = await client.get(f"{_API_PACKAGE_URL}/{full_name}")
            if resp.status_code != 200:
                return None
            data = resp.json()
            return data if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            return None

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Anaconda.org for conda packages matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        qp = {"name": query}
        async with self._client() as client:
            resp = await client.get(_API_SEARCH_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                return ProviderResult(results=[])

            # Enrich the top hits with fresh metadata when the search
            # index omitted the latest version.
            for item in self._dedupe_packages(data)[:limit]:
                if _clean(item.get("latest_version")):
                    continue
                full_name = _clean(item.get("full_name"))
                if not full_name:
                    continue
                meta = await self._fetch_package_meta(client, full_name)
                if meta:
                    latest = _clean(meta.get("latest_version"))
                    if latest:
                        item["latest_version"] = latest

        return self._parse(data, limit=limit)
