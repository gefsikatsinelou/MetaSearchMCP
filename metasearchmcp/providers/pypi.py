from __future__ import annotations

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

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
    tags = ["web", "code", "developer", "packages"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        # Candidate names to probe: whole query + individual tokens
        candidates: list[str] = []
        slug = query.strip().lower().replace(" ", "-")
        if slug:
            candidates.append(slug)
        for token in query.lower().split():
            t = token.strip(".,;:()[]")
            if t and t not in candidates:
                candidates.append(t)

        results: list[SearchResult] = []
        seen: set[str] = set()

        async with self._client() as client:
            for name in candidates:
                if len(results) >= min(params.num_results, self._max_results):
                    break
                if name in seen:
                    continue
                seen.add(name)
                try:
                    resp = await client.get(_JSON_API.format(name=name))
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                except Exception:
                    continue

                info = data.get("info", {})
                pkg_name = info.get("name", name)
                version = info.get("version", "")
                summary = info.get("summary", "") or ""
                home_page = info.get("home_page", "") or ""
                project_url = info.get(
                    "package_url",
                    f"https://pypi.org/project/{pkg_name}/",
                )
                keywords = (info.get("keywords") or "").split(",")[:5]

                snippet_parts = [summary]
                if version:
                    snippet_parts.append(f"v{version}")
                if keywords and keywords != [""]:
                    snippet_parts.append(
                        f"Keywords: {', '.join(k.strip() for k in keywords if k.strip())}",
                    )

                results.append(
                    SearchResult(
                        title=pkg_name,
                        url=project_url,
                        snippet=" | ".join(p for p in snippet_parts if p),
                        source="pypi.org",
                        rank=len(results) + 1,
                        provider=self.name,
                        extra={
                            "version": version,
                            "author": info.get("author", ""),
                            "license": info.get("license", ""),
                            "requires_python": info.get("requires_python", ""),
                            "home_page": home_page,
                        },
                    ),
                )

        return ProviderResult(results=results)
