"""Docker Hub repository search via the public search API."""

from __future__ import annotations

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://hub.docker.com/v2/search/repositories/"
_MAX_API_RESULTS = 25


class DockerHubProvider(BaseProvider):
    """Docker Hub repository search via the public search API."""

    name = "dockerhub"
    description = "Search public container images on Docker Hub."
    tags = ["web", "code", "developer", "containers"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Docker Hub for *query* and return image results."""
        qp = {
            "query": query,
            "page_size": min(params.num_results, self._max_results, _MAX_API_RESULTS),
            "page": 1,
        }

        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []

        for i, item in enumerate(data.get("summaries", []), start=1):
            name = item.get("name", "")
            namespace = item.get("namespace", "")
            repo_name = f"{namespace}/{name}" if namespace else name
            description = item.get("short_description", "") or ""
            stars = item.get("star_count", 0)
            pulls = item.get("pull_count", 0)

            snippet_parts = [description]
            snippet_parts.append(f"Stars: {stars}")
            if pulls:
                snippet_parts.append(f"Pulls: {pulls:,}")

            results.append(
                SearchResult(
                    title=repo_name,
                    url=f"https://hub.docker.com/r/{repo_name}",
                    snippet=" | ".join(part for part in snippet_parts if part),
                    source="hub.docker.com",
                    rank=i,
                    provider=self.name,
                    extra={
                        "star_count": stars,
                        "pull_count": pulls,
                        "is_official": item.get("is_official", False),
                    },
                ),
            )

        return ProviderResult(results=results)
