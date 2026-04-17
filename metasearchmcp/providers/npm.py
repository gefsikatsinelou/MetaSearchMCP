from __future__ import annotations

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider

_API_URL = "https://registry.npmjs.org/-/v1/search"


class NpmProvider(BaseProvider):
    """npm package search via the npm registry API.

    Fully public, no authentication required.
    """

    name = "npm"
    description = "Search JavaScript and TypeScript packages on the npm registry."
    tags = ["web", "code", "developer", "packages"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        qp = {
            "text": query,
            "size": min(params.num_results, self._max_results, 20),
        }

        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []

        for i, obj in enumerate(data.get("objects", []), start=1):
            pkg = obj.get("package", {})
            name = pkg.get("name", "")
            version = pkg.get("version", "")
            description = pkg.get("description", "")
            keywords = pkg.get("keywords", [])
            date = (pkg.get("date") or "")[:10]
            links = pkg.get("links", {})
            url = links.get("npm", f"https://www.npmjs.com/package/{name}")

            snippet_parts = [description]
            if keywords:
                snippet_parts.append(f"Keywords: {', '.join(keywords[:5])}")
            if version:
                snippet_parts.append(f"v{version}")

            results.append(SearchResult(
                title=name,
                url=url,
                snippet=" | ".join(p for p in snippet_parts if p),
                source="npmjs.com",
                rank=i,
                provider=self.name,
                published_date=date or None,
                extra={
                    "version": version,
                    "keywords": keywords,
                    "links": links,
                    "score": obj.get("score", {}),
                },
            ))

        return ProviderResult(results=results)
