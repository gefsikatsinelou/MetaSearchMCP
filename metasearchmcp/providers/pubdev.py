"""pub.dev (Dart/Flutter) package search via the official keyless JSON API.

pub.dev is the default package repository for the Dart ecosystem (used by
both Dart and Flutter projects). Its read-only JSON API requires no key:

``GET https://pub.dev/api/search?q=QUERY&page=N``

The search index returns ranked package names; the provider then fetches
per-package metadata from ``/api/packages/NAME`` for each hit (reusing one
HTTP session), which yields the latest version, description, repository
URL, topic tags, and published date. Results link to the canonical
``pub.dev/packages/NAME`` landing page (or the package's repository when
one is declared).
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_SEARCH_URL = "https://pub.dev/api/search"
_API_PACKAGE_URL = "https://pub.dev/api/packages"
# HTML landing pages live under /packages, distinct from the /api/ endpoints.
_CANONICAL_URL = "https://pub.dev/packages"


def _clean(value: object) -> str:
    """Collapse whitespace and control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _name_only(value: str) -> str:
    """Strip an optional ``name@version`` suffix from a search hit."""
    return value.split("@", 1)[0].strip() if value else ""


class PubDevProvider(BaseProvider):
    """Search Dart/Flutter packages published on pub.dev.

    Keyless. Uses the official ``/api/search`` index plus per-package
    metadata lookups, covering the whole pub.dev catalog including Flutter
    plugins and pure Dart libraries. Each hit carries the latest version,
    description, repository, topic tags, and published date, linked to the
    canonical pub.dev landing page.
    """

    name = "pubdev"
    description = (
        "Search Dart/Flutter packages published on pub.dev, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "packages"]

    @staticmethod
    def _parse_search_hits(data: object) -> list[str]:
        """Return the ordered package names from a search response.

        Entries may be plain strings or objects with a ``package`` field;
        entries without a usable name are skipped.
        """
        names: list[str] = []
        packages = data.get("packages") if isinstance(data, dict) else None
        if not isinstance(packages, list):
            return names
        for entry in packages:
            raw = (
                entry
                if isinstance(entry, str)
                else (entry.get("package") if isinstance(entry, dict) else "")
            )
            name = _name_only(_clean(raw))
            if name and name not in names:
                names.append(name)
        return names

    def _result_from_meta(
        self, name: str, data: object, rank: int
    ) -> SearchResult | None:
        """Build a result from a per-package metadata response."""
        if not isinstance(data, dict):
            return None
        latest = data.get("latest")
        if not isinstance(latest, dict):
            return None
        pubspec = latest.get("pubspec")
        if not isinstance(pubspec, dict):
            pubspec = {}

        description = _clean(pubspec.get("description"))
        repository = _clean(pubspec.get("repository"))
        version = _clean(latest.get("version"))
        if not version:
            version = _clean(pubspec.get("version"))
        published = _clean(latest.get("published"))
        topics = pubspec.get("topics") or []
        if not isinstance(topics, list):
            topics = []

        url = repository or f"{_CANONICAL_URL}/{name}"
        snippet_parts: list[str] = [description]
        if version:
            snippet_parts.append(f"v{version}")
        if topics:
            snippet_parts.append("Topics: " + ", ".join(_clean(t) for t in topics[:5]))

        return SearchResult(
            title=name,
            url=url,
            snippet=" | ".join(p for p in snippet_parts if p)[:MAX_SNIPPET_LENGTH],
            source="pub.dev",
            rank=rank,
            provider=self.name,
            published_date=published[:10] or None,
            extra={
                "package_name": name,
                "version": version,
                "description": description,
                "repository": repository,
                "topics": [_clean(t) for t in topics],
                "published_at": published,
            },
        )

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search pub.dev for Dart/Flutter packages matching *query*."""
        limit = min(params.num_results, self._max_results)
        qp = {"q": query, "page": "1"}
        async with self._client() as client:
            resp = await client.get(_API_SEARCH_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

            names = self._parse_search_hits(data)[:limit]
            results: list[SearchResult] = []
            for name in names:
                if len(results) >= limit:
                    break
                meta = await self._fetch_package_meta(client, name)
                result = self._result_from_meta(name, meta, rank=len(results) + 1)
                if result is not None:
                    results.append(result)

        return ProviderResult(results=results)

    async def _fetch_package_meta(
        self, client: httpx.AsyncClient, name: str
    ) -> dict[str, Any] | None:
        """Fetch metadata for a single package from the JSON API."""
        try:
            resp = await client.get(f"{_API_PACKAGE_URL}/{name}")
            if resp.status_code != 200:
                return None
            data = resp.json()
            return data if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            return None
