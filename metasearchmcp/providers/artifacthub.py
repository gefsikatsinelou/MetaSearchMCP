"""Artifact Hub package search via the public keyless API.

Artifact Hub is a central index for cloud-native packages across many
repositories and kinds: Helm charts, OLM operators, Falco rules, OPA /
Gatekeeper / Kyverno / Kubewarden policies, Tekton tasks and pipelines,
Krew plugins, container images, Backstage plugins, and more. Its
read-only search API requires no API key:

``GET https://artifacthub.io/api/v1/packages/search?ts_query_web=QUERY&limit=N``

Each hit carries the package name, description, latest version, star
count, publisher repository, and (when present) the license. Artifact Hub
complements the existing registry providers (npm, PyPI, Hex, Maven,
Docker Hub, ...) with the Kubernetes / cloud-native ecosystem, which none
of them cover.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://artifacthub.io/api/v1/packages/search"

# Artifact Hub repository kinds (the ``repository.kind`` integer) mapped to
# the path segment used by package pages on artifacthub.io. Unknown kinds
# fall back to a scoped site search so links remain valid.
_KIND_SLUGS: dict[int, str] = {
    0: "helm",
    1: "falco",
    2: "opa",
    3: "olm",
    4: "tinkerbell-action",
    5: "krew-plugin",
    6: "helm-plugin",
    7: "tekton-task",
    8: "keda-scaler",
    9: "coredns-plugin",
    10: "keptn-integration",
    11: "tekton-pipeline",
    12: "container",
    13: "kubewarden-policy",
    14: "gatekeeper-policy",
    15: "kyverno-policy",
    16: "knative-client",
    17: "backstage-plugin",
    18: "argo-template",
    19: "kubearmor-policy",
    20: "kcl-module",
    21: "headlamp-plugin",
    22: "inspektor-gadget",
}


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


class ArtifactHubProvider(BaseProvider):
    """Search cloud-native packages indexed by Artifact Hub.

    Keyless. Covers Helm charts, OLM operators, policy packs (OPA,
    Gatekeeper, Kyverno, Kubewarden), Tekton tasks and pipelines, Krew
    plugins, container images, and more. Each hit carries the package
    name, description, version, star count, and publisher repository.
    """

    name = "artifacthub"
    description = (
        "Search cloud-native packages (Helm charts, operators, policies, "
        "container images) indexed by Artifact Hub, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "kubernetes", "packages"]

    @staticmethod
    def _package_url(kind: object, repository_name: str, package_name: str) -> str:
        """Build the artifacthub.io page URL for a package.

        Falls back to a scoped site search when the repository kind is
        unknown so the returned link always resolves to something useful.
        """
        slug = _KIND_SLUGS.get(kind) if isinstance(kind, int) else None
        if slug and repository_name:
            return (
                f"https://artifacthub.io/packages/{slug}/"
                f"{quote(repository_name, safe='')}/{quote(package_name, safe='')}"
            )
        return (
            f"https://artifacthub.io/packages/search?ts_query_web={quote(package_name)}"
        )

    @staticmethod
    def _published(ts: object) -> str | None:
        """Convert a Unix timestamp (seconds) to a ``YYYY-MM-DD`` string."""
        if not isinstance(ts, (int, float)) or isinstance(ts, bool) or ts <= 0:
            return None
        return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse an Artifact Hub search response into structured results."""
        results: list[SearchResult] = []
        packages = data.get("packages") if isinstance(data, dict) else data
        if not isinstance(packages, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in packages:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            name = _clean(item.get("name"))
            if not name:
                continue

            repository = item.get("repository")
            if not isinstance(repository, dict):
                repository = {}
            repo_name = _clean(repository.get("name"))
            repo_display = _clean(repository.get("display_name")) or repo_name
            kind = repository.get("kind")

            description = _clean(item.get("description"))
            version = _clean(item.get("version"))
            app_version = _clean(item.get("app_version"))
            raw_stars = item.get("stars")
            stars = raw_stars if isinstance(raw_stars, int) else 0
            license_text = _clean(item.get("license"))

            snippet_parts: list[str] = [description]
            if version:
                snippet_parts.append(f"v{version}")
            if stars:
                snippet_parts.append(f"Stars: {stars:,}")
            if repo_display:
                snippet_parts.append(f"Repo: {repo_display}")

            results.append(
                SearchResult(
                    title=name,
                    url=self._package_url(kind, repo_name, name),
                    snippet=" | ".join(p for p in snippet_parts if p)[
                        :MAX_SNIPPET_LENGTH
                    ],
                    source="artifacthub.io",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=self._published(item.get("ts")),
                    extra={
                        "package_name": name,
                        "version": version,
                        "app_version": app_version,
                        "stars": stars,
                        "license": license_text,
                        "repository": repo_name,
                        "repository_display_name": repo_display,
                        "repository_url": _clean(repository.get("url")),
                        "repository_kind": kind if isinstance(kind, int) else None,
                        "official": bool(repository.get("official")),
                        "verified_publisher": bool(
                            repository.get("verified_publisher")
                        ),
                        "deprecated": bool(item.get("deprecated")),
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Artifact Hub for cloud-native packages matching *query*."""
        limit = min(params.num_results, self._max_results)
        qp = {"ts_query_web": query, "limit": str(limit), "offset": "0"}
        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
