"""GitHub repository search via the public REST API."""

from __future__ import annotations

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://api.github.com/search/repositories"
_MAX_API_RESULTS = 30


class GitHubProvider(BaseProvider):
    """GitHub repository search via the public REST API.

    No token: 10 req/min (unauthenticated).
    With GITHUB_TOKEN: 30 req/min, higher rate limits.
    """

    name = "github"
    description = "Search GitHub repositories, code, issues, and pull requests."
    tags = ["code", "web"]

    def __init__(self) -> None:
        """Initialize the GitHub provider with an optional API token."""
        super().__init__()
        self._token = get_settings().github_token

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search GitHub repositories for *query*."""
        qp = {
            "q": query,
            "per_page": str(
                min(params.num_results, self._max_results, _MAX_API_RESULTS),
            ),
            "sort": "best-match",
        }
        headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []

        for i, item in enumerate(data.get("items", []), start=1):
            description = item.get("description") or ""
            stars = item.get("stargazers_count", 0)
            language = item.get("language") or ""

            snippet_parts = [description]
            if language:
                snippet_parts.append(f"Language: {language}")
            snippet_parts.append(f"Stars: {stars}")

            results.append(
                SearchResult(
                    title=item.get("full_name", ""),
                    url=item.get("html_url", ""),
                    snippet=" | ".join(p for p in snippet_parts if p),
                    source="github.com",
                    rank=i,
                    provider=self.name,
                    published_date=item.get("pushed_at", "")[:10] or None,
                    extra={
                        "stars": stars,
                        "language": language,
                        "forks": item.get("forks_count", 0),
                        "topics": item.get("topics", []),
                    },
                ),
            )

        return ProviderResult(results=results)
