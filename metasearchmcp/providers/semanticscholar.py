from __future__ import annotations

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_FIELDS = "paperId,title,abstract,year,authors,url,externalIds,venue,citationCount"


class SemanticScholarProvider(BaseProvider):
    """Semantic Scholar academic paper search via the public Graph API.

    Unauthenticated: 1 req/sec, 5,000 req/day.
    With a free API key: 10 req/sec, 100M+ papers indexed.
    Sign up at https://www.semanticscholar.org/product/api and set
    SEMANTIC_SCHOLAR_API_KEY env var.
    """

    name = "semanticscholar"
    description = (
        "Search academic papers with AI-powered semantic "
        "understanding via Semantic Scholar."
    )
    tags = ["academic", "web"]

    def __init__(self) -> None:
        super().__init__()
        from metasearchmcp.config import get_settings

        settings = get_settings()
        self._api_key: str = getattr(settings, "semantic_scholar_api_key", "")

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        qp = {
            "query": query,
            "limit": min(params.num_results, self._max_results, 10),
            "fields": _FIELDS,
        }
        headers: dict[str, str] = {}
        if self._api_key:
            headers["x-api-key"] = self._api_key

        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []

        for i, paper in enumerate(data.get("data", []), start=1):
            title = paper.get("title", "")
            abstract = (paper.get("abstract") or "")[:400]
            year = str(paper.get("year") or "")
            venue = paper.get("venue", "") or ""
            citations = paper.get("citationCount", 0)

            authors_raw = paper.get("authors", [])
            authors = [a.get("name", "") for a in authors_raw[:3]]
            if len(authors_raw) > 3:
                authors.append("et al.")

            # Prefer DOI URL, fall back to S2 URL
            ext_ids = paper.get("externalIds") or {}
            doi = ext_ids.get("DOI", "")
            paper_id = paper.get("paperId", "")
            url = (
                f"https://doi.org/{doi}"
                if doi
                else f"https://www.semanticscholar.org/paper/{paper_id}"
            )

            snippet_parts = [abstract]
            if venue:
                snippet_parts.append(venue)
            if authors:
                snippet_parts.append(", ".join(authors))
            if citations:
                snippet_parts.append(f"Cited by: {citations}")

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(p for p in snippet_parts if p),
                    source="semanticscholar.org",
                    rank=i,
                    provider=self.name,
                    published_date=year or None,
                    extra={
                        "paper_id": paper_id,
                        "year": paper.get("year"),
                        "citation_count": citations,
                        "authors": [a.get("name", "") for a in authors_raw],
                        "doi": doi,
                    },
                ),
            )

        return ProviderResult(results=results)
