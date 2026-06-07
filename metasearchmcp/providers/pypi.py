"""PyPI package lookup via the JSON API."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

if TYPE_CHECKING:
    import httpx

from .base import BaseProvider

logger = logging.getLogger(__name__)

_JSON_API = "https://pypi.org/pypi/{name}/json"
_SEARCH_URL = "https://pypi.org/search/"


class PyPIProvider(BaseProvider):
    """PyPI package lookup via the JSON API.

    PyPI's HTML search page is protected by Cloudflare bot detection and
    cannot be scraped reliably. The XML-RPC search method was removed.

    This provider uses the per-package JSON API endpoint:
      https://pypi.org/pypi/{name}/json

    For the given query it tries exact-name lookup first, then splits the
    query on spaces and tries each token. This works well when the query is
    a specific package name (e.g. "httpx", "pydantic v2"). For general
    keyword queries the results will be sparse.
    """

    name = "pypi"
    description = "Search Python packages published on PyPI."
    tags: ClassVar[list[str]] = ["web", "code", "developer", "packages"]

    @staticmethod
    def _build_candidates(query: str) -> list[str]:
        """Build a list of candidate package names from the query."""
        candidates: list[str] = []
        slug = query.strip().lower().replace(" ", "-")
        if slug:
            candidates.append(slug)
        for token in query.lower().split():
            t = token.strip(".,;:()[]")
            if t and t not in candidates:
                candidates.append(t)
        return candidates

    @staticmethod
    def _build_snippet(info: dict[str, Any]) -> str:
        """Build a human-readable snippet from package metadata."""
        summary = info.get("summary", "") or ""
        version = info.get("version", "")
        keywords_raw = info.get("keywords") or ""
        keywords = keywords_raw.split(",")[:5]

        parts: list[str] = [summary]
        if version:
            parts.append(f"v{version}")
        if keywords and keywords != [""]:
            joined = ", ".join(k.strip() for k in keywords if k.strip())
            parts.append(f"Keywords: {joined}")

        return " | ".join(p for p in parts if p)

    async def _fetch_package_info(
        self,
        client: httpx.AsyncClient,
        name: str,
    ) -> dict[str, Any] | None:
        """Fetch package metadata from the PyPI JSON API."""
        try:
            resp = await client.get(_JSON_API.format(name=name))
            if resp.status_code != HTTPStatus.OK:
                return None
            return resp.json()
        except Exception:
            logger.exception("PyPI lookup failed for %s", name)
            return None

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search PyPI for Python packages matching *query*."""
        candidates = self._build_candidates(query)
        max_results = min(params.num_results, self._max_results)

        results: list[SearchResult] = []
        seen: set[str] = set()

        async with self._client() as client:
            for name in candidates:
                if len(results) >= max_results:
                    break
                if name in seen:
                    continue
                seen.add(name)

                data = await self._fetch_package_info(client, name)
                if data is None:
                    continue

                info = data.get("info", {})
                pkg_name = info.get("name", name)
                project_url = info.get(
                    "package_url",
                    f"https://pypi.org/project/{pkg_name}/",
                )

                results.append(
                    SearchResult(
                        title=pkg_name,
                        url=project_url,
                        snippet=self._build_snippet(info),
                        source="pypi.org",
                        rank=len(results) + 1,
                        provider=self.name,
                        extra={
                            "version": info.get("version", ""),
                            "author": info.get("author", ""),
                            "license": info.get("license", ""),
                            "requires_python": info.get("requires_python", ""),
                            "home_page": info.get("home_page", "") or "",
                        },
                    ),
                )

        return ProviderResult(results=results)
