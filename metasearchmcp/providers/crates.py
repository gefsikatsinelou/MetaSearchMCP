from __future__ import annotations

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import API_USER_AGENT, BaseProvider

_API_URL = "https://crates.io/api/v1/crates"


class CratesIoProvider(BaseProvider):
    """crates.io Rust package search via the public REST API.

    No authentication required.
    """

    name = "crates"
    description = "Search Rust packages published on crates.io."
    tags = ["web", "code", "developer", "packages"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        qp = {
            "q": query,
            "per_page": min(params.num_results, self._max_results, 10),
        }
        # crates.io requires a descriptive User-Agent
        headers = {
            "User-Agent": API_USER_AGENT,
        }

        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []

        for i, crate in enumerate(data.get("crates", []), start=1):
            name = crate.get("name", "")
            version = crate.get("newest_version", "")
            description = crate.get("description", "") or ""
            downloads = crate.get("downloads", 0)
            updated = (crate.get("updated_at") or "")[:10]
            url = f"https://crates.io/crates/{name}"

            snippet_parts = [description]
            snippet_parts.append(f"v{version}" if version else "")
            snippet_parts.append(f"Downloads: {downloads:,}")

            results.append(
                SearchResult(
                    title=name,
                    url=url,
                    snippet=" | ".join(p for p in snippet_parts if p),
                    source="crates.io",
                    rank=i,
                    provider=self.name,
                    published_date=updated or None,
                    extra={
                        "version": version,
                        "downloads": downloads,
                        "recent_downloads": crate.get("recent_downloads", 0),
                    },
                ),
            )

        return ProviderResult(results=results)
