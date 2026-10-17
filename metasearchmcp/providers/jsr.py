"""JSR (@jsr) JavaScript/TypeScript package search via the keyless JSR API.

`JSR <https://jsr.io>`_ — the JavaScript Registry — is the modern,
ESM-native package registry for JavaScript and TypeScript, built by the
Deno team.  Its packages run on Deno, Node.js, Bun, browsers and
Cloudflare Workers.  The read-only search API requires no key:

``GET https://jsr.io/api/packages?query=QUERY&limit=N&page=P``

The response is ``{"items": [...], "total": N}`` where each item carries
the package ``scope`` and ``name``, an optional description, the latest
published version, version/dependency/dependent counts, a relevance
``score``, per-runtime compatibility flags, the linked GitHub repository
and an archival flag.  A package is addressed as ``@scope/name``.

JSR complements the existing JavaScript-ecosystem coverage — ``npm``
indexes the npm registry, ``cdnjs`` the CDNJS library index, and
``open_vsx`` / ``vscode_marketplace`` the extension marketplaces — but
not the Deno-native JSR registry.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://jsr.io/api/packages"
# JSR caps a single page at 100 items; requests are always well below this.
_PAGE_SIZE = 100


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _runtimes(value: object) -> list[str]:
    """Return the sorted runtime names a package claims compatibility with."""
    if not isinstance(value, dict):
        return []
    return sorted(name for name, supported in value.items() if supported)


class JsrProvider(BaseProvider):
    """Search JavaScript/TypeScript packages published on the JSR registry.

    Keyless.  Uses the official ``/api/packages`` search endpoint, which
    covers the whole JSR catalog including ``@std``, ``@oak/oak`` and
    general Deno/Node packages.  Each hit carries the ``@scope/name``
    package identifier, latest version, description, relevance score,
    version/dependency/dependent counts and the linked source repository.
    """

    name = "jsr"
    description = (
        "Search JavaScript/TypeScript packages published on the JSR "
        "registry (the ESM-native registry for Deno, Node.js, Bun and "
        "browsers), no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "packages"]

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a JSR search response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        items = data.get("items")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in items:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue

            scope = _clean(item.get("scope"))
            name = _clean(item.get("name"))
            if not scope or not name:
                continue

            package = f"@{scope}/{name}"
            description = _clean(item.get("description"))
            version = _clean(item.get("latestVersion"))
            score = item.get("score")
            version_count = item.get("versionCount")
            dependent_count = item.get("dependentCount")

            runtime_names = _runtimes(item.get("runtimeCompat"))
            repo = item.get("githubRepository")
            repo_slug = ""
            if isinstance(repo, dict):
                owner = _clean(repo.get("owner"))
                repo_name = _clean(repo.get("name"))
                repo_slug = f"{owner}/{repo_name}" if owner and repo_name else ""

            snippet_parts: list[str] = [description]
            if version:
                snippet_parts.append(f"v{version}")
            if isinstance(score, int):
                snippet_parts.append(f"score {score}")
            if isinstance(version_count, int) and version_count:
                snippet_parts.append(f"{version_count} versions")
            if isinstance(dependent_count, int) and dependent_count:
                snippet_parts.append(f"{dependent_count} dependents")
            if runtime_names:
                snippet_parts.append("runs on " + ", ".join(runtime_names))

            results.append(
                SearchResult(
                    title=package,
                    url=f"https://jsr.io/{package}",
                    snippet=" | ".join(p for p in snippet_parts if p)[
                        :MAX_SNIPPET_LENGTH
                    ],
                    source="jsr.io",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "package": package,
                        "scope": scope,
                        "name": name,
                        "latest_version": version,
                        "version_count": version_count,
                        "dependency_count": item.get("dependencyCount"),
                        "dependent_count": dependent_count,
                        "score": score,
                        "runtime_compat": runtime_names,
                        "github_repo": repo_slug,
                        "is_archived": bool(item.get("isArchived")),
                        "updated_at": _clean(item.get("updatedAt")),
                        "created_at": _clean(item.get("createdAt")),
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the JSR registry for JavaScript/TypeScript packages."""
        limit = min(params.num_results, self._max_results)
        qp: dict[str, Any] = {"query": query, "limit": min(limit, _PAGE_SIZE)}
        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
