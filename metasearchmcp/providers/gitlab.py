from __future__ import annotations

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_BASE_URL = "https://gitlab.com"
_API_PATH = "api/v4/projects"


class GitLabProvider(BaseProvider):
    """GitLab project search via the public GitLab REST API.

    No authentication required for public project search.
    """

    name = "gitlab"
    description = "Search GitLab projects and repositories."
    tags = ["web", "code", "developer", "repos"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        async with self._client() as client:
            resp = await client.get(
                f"{_BASE_URL}/{_API_PATH}",
                params={"search": query, "per_page": min(params.num_results, 20)},
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: list) -> ProviderResult:
        results: list[SearchResult] = []

        for i, item in enumerate(data, start=1):
            name = item.get("name", "")
            url = item.get("web_url", "")
            description = item.get("description") or ""
            namespace = (item.get("namespace") or {}).get("full_path", "")
            stars = item.get("star_count", 0)
            last_active = (item.get("last_activity_at") or "")[:10]

            snippet_parts = [description]
            if namespace:
                snippet_parts.append(f"Namespace: {namespace}")
            if stars:
                snippet_parts.append(f"Stars: {stars}")

            results.append(
                SearchResult(
                    title=item.get("name_with_namespace", name),
                    url=url,
                    snippet=" | ".join(p for p in snippet_parts if p),
                    source="gitlab.com",
                    rank=i,
                    provider=self.name,
                    published_date=last_active or None,
                    extra={
                        "stars": stars,
                        "forks": item.get("forks_count", 0),
                        "language": item.get("default_branch"),
                        "topics": item.get("topics", []),
                        "clone_url": item.get("http_url_to_repo"),
                    },
                ),
            )

        return ProviderResult(results=results)
