"""Cross-distribution package search via the keyless Repology API.

`Repology <https://repology.org>`_ aggregates packaging information from well
over a hundred software repositories — Linux distributions (Debian, Fedora,
Arch, Alpine, NixOS, Gentoo, ...), language package managers (PyPI, npm,
crates.io, CPAN, ...), and portable collections (Homebrew, *BSD ports).  For a
given project it shows which version each repository ships, whether a package
is up to date, outdated or legacy, and who maintains it.

Its read-only API is keyless:

``GET https://repology.org/api/v1/projects/?search=QUERY``

The response is a JSON object keyed by *project name*, where each value is a
list of per-repository package entries carrying ``repo``, ``srcname``,
``visiblename``, ``version``, ``status``, ``summary``, ``maintainers``,
``licenses`` and ``categories``.

A search returns one result per matching project, ranked by how many
repositories package it (the strongest signal of notability).  This
complements the language-specific registry providers (``pypi``, ``npm``,
``crates``, ``jsr``, ...) by indexing *which distributions* ship a project and
*which version* each one carries.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://repology.org/api/v1/projects/"
# Number of projects (dict keys) turned into results.
_MAX_PROJECTS = 10
# Maximum per-repository entries embedded in a result's ``extra`` payload.
_MAX_REPOS_IN_EXTRA = 25


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _str_list(value: object) -> list[str]:
    """Return a cleaned list of strings from a JSON array field."""
    if not isinstance(value, list):
        return []
    return [text for text in (_clean(item) for item in value) if text]


class RepologyProvider(BaseProvider):
    """Search software projects across distribution repositories.

    Keyless.  Uses the public Repology ``/api/v1/projects/`` search endpoint.
    Each result is one project (e.g. ``curl``, ``python``, ``openssl``) with
    its latest version, the repositories that package it, license info and
    maintainers, plus the full per-repository version table in ``extra``.
    """

    name = "repology"
    description = (
        "Search software projects across 100+ distribution and language "
        "repositories (Debian, Fedora, Arch, Alpine, NixOS, Homebrew, PyPI, "
        "npm, ...) for per-repository versions, outdated/newest status, "
        "licenses and maintainers via the keyless Repology API — no API key "
        "required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "packages"]

    @staticmethod
    def _repo_entry(item: dict[str, Any]) -> dict[str, str]:
        """Normalize one per-repository package entry."""
        return {
            "repo": _clean(item.get("repo")),
            "subrepo": _clean(item.get("subrepo")),
            "srcname": _clean(item.get("srcname")) or _clean(item.get("binname")),
            "version": _clean(item.get("version")) or _clean(item.get("origversion")),
            "status": _clean(item.get("status")),
        }

    @staticmethod
    def _latest_version(entries: list[dict[str, str]]) -> str:
        """Pick the most authoritative version across repository entries.

        Prefers an entry flagged ``newest`` by Repology, else the first
        non-empty version seen.
        """
        for entry in entries:
            if entry["status"] == "newest" and entry["version"]:
                return entry["version"]
        for entry in entries:
            if entry["version"]:
                return entry["version"]
        return ""

    def _project_result(
        self,
        project: str,
        raw_entries: object,
    ) -> SearchResult | None:
        """Build one result for *project* from its repository entries."""
        if not isinstance(raw_entries, list):
            return None
        entries = [
            self._repo_entry(item) for item in raw_entries if isinstance(item, dict)
        ]
        if not entries:
            return None

        # Summary/licenses/maintainers/categories come from the first entry
        # that carries them (they are project-level, duplicated per repo).
        first = next((item for item in raw_entries if isinstance(item, dict)), {})
        summary = _clean(first.get("summary"))
        licenses = _str_list(first.get("licenses"))
        categories = _str_list(first.get("categories"))
        maintainers = _str_list(first.get("maintainers"))

        versions = sorted({entry["version"] for entry in entries if entry["version"]})
        latest = self._latest_version(entries)
        repo_count = len({entry["repo"] for entry in entries if entry["repo"]})
        statuses = sorted({entry["status"] for entry in entries if entry["status"]})

        snippet_parts: list[str] = []
        if summary:
            snippet_parts.append(summary)
        if latest:
            snippet_parts.append(f"latest {latest}")
        if repo_count:
            snippet_parts.append(f"in {repo_count} repositories")
        if len(versions) > 1:
            snippet_parts.append(f"{len(versions)} distinct versions")
        if statuses:
            snippet_parts.append("status: " + ", ".join(statuses))

        project_url = f"https://repology.org/project/{quote(project, safe='')}"
        return SearchResult(
            title=project,
            url=f"{project_url}/versions",
            snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
            source="repology.org",
            provider=self.name,
            extra={
                "project": project,
                "summary": summary,
                "latest_version": latest,
                "versions": versions,
                "repo_count": repo_count,
                "statuses": statuses,
                "licenses": licenses,
                "categories": categories,
                "maintainers": maintainers,
                "repositories": entries[:_MAX_REPOS_IN_EXTRA],
                "project_url": project_url,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a Repology ``/projects/`` response into structured results."""
        if not isinstance(data, dict):
            return ProviderResult(results=[])

        max_results = limit or self._max_results
        candidates: list[tuple[int, str, object]] = []
        for project, entries in data.items():
            if not isinstance(project, str) or not project:
                continue
            repo_count = (
                len(
                    {
                        e["repo"]
                        for e in entries
                        if isinstance(e, dict) and e.get("repo")
                    }
                )
                if isinstance(entries, list)
                else 0
            )
            candidates.append((repo_count, project, entries))

        # Most widely-packaged projects first, then alphabetical for stability.
        candidates.sort(key=lambda item: (-item[0], item[1]))

        results: list[SearchResult] = []
        for _repo_count, project, entries in candidates:
            if len(results) >= max_results:
                break
            result = self._project_result(project, entries)
            if result is None:
                continue
            result.rank = len(results) + 1
            results.append(result)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Repology for software projects matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_PROJECTS)
        async with self._client() as client:
            resp = await client.get(_API_URL, params={"search": query})
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
