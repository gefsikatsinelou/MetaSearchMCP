from __future__ import annotations

import copy

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider

_SEARCH_URL = "https://fastapi.metacpan.org/v1/file/_search"

_QUERY_TEMPLATE = {
    "query": {
        "multi_match": {
            "type": "most_fields",
            "fields": ["documentation", "documentation.*"],
            "analyzer": "camelcase",
        }
    },
    "filter": {
        "bool": {
            "must": [
                {"exists": {"field": "documentation"}},
                {"term": {"status": "latest"}},
                {"term": {"indexed": 1}},
                {"term": {"authorized": 1}},
            ]
        }
    },
    "sort": [
        {"_score": {"order": "desc"}},
        {"date": {"order": "desc"}},
    ],
    "_source": ["documentation", "abstract"],
}


class MetaCPANProvider(BaseProvider):
    """MetaCPAN — CPAN Perl module search via the MetaCPAN API.

    Public API, no authentication required.
    """

    name = "metacpan"
    description = "Search Perl modules and distributions on MetaCPAN."
    tags = ["web", "code", "developer", "packages"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        num = min(params.num_results, self._max_results, 20)
        payload = copy.deepcopy(_QUERY_TEMPLATE)
        payload["query"]["multi_match"]["query"] = query  # type: ignore[index]
        payload["size"] = num
        payload["from"] = 0

        async with self._client() as client:
            resp = await client.post(_SEARCH_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []

        hits = data.get("hits", {}).get("hits", [])
        for i, hit in enumerate(hits, start=1):
            fields = hit.get("_source", {})
            module = fields.get("documentation", "")
            abstract = fields.get("abstract", "")
            results.append(
                SearchResult(
                    title=module,
                    url=f"https://metacpan.org/pod/{module}",
                    snippet=abstract,
                    source="metacpan.org",
                    rank=i,
                    provider=self.name,
                )
            )

        return ProviderResult(results=results)
