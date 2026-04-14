from __future__ import annotations

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


class PubMedProvider(BaseProvider):
    """PubMed biomedical literature search via NCBI E-utilities.

    Fully public, no API key required for low-volume use.
    Recommended rate: <= 3 req/sec without key. For higher volume,
    register for a free API key at https://ncbiinsights.ncbi.nlm.nih.gov/api-key-signup/
    and set NCBI_API_KEY env var.
    """

    name = "pubmed"
    tags = ["academic", "web", "medical"]

    def __init__(self) -> None:
        super().__init__()
        from metasearchmcp.config import get_settings
        settings = get_settings()
        self._api_key: str = getattr(settings, "ncbi_api_key", "")

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        limit = min(params.num_results, self._max_results, 10)

        # Step 1: ESearch — get PMIDs
        esearch_params: dict = {
            "db": "pubmed",
            "term": query,
            "retmax": limit,
            "retmode": "json",
            "sort": "relevance",
        }
        if self._api_key:
            esearch_params["api_key"] = self._api_key

        async with self._client() as client:
            r = await client.get(_ESEARCH_URL, params=esearch_params)
            r.raise_for_status()
            ids = r.json().get("esearchresult", {}).get("idlist", [])

            if not ids:
                return ProviderResult()

            # Step 2: ESummary — get article metadata
            esummary_params: dict = {
                "db": "pubmed",
                "id": ",".join(ids),
                "retmode": "json",
            }
            if self._api_key:
                esummary_params["api_key"] = self._api_key

            s = await client.get(_ESUMMARY_URL, params=esummary_params)
            s.raise_for_status()
            summary_data = s.json()

        return self._parse(summary_data, ids)

    def _parse(self, data: dict, ids: list[str]) -> ProviderResult:
        results: list[SearchResult] = []
        result_map = data.get("result", {})

        for i, pmid in enumerate(ids, start=1):
            item = result_map.get(pmid, {})
            if not item:
                continue

            title = item.get("title", "")
            pub_date = item.get("pubdate", "")[:10]
            journal = item.get("source", "")
            authors_raw = item.get("authors", [])
            authors = [a.get("name", "") for a in authors_raw[:3]]
            if len(authors_raw) > 3:
                authors.append("et al.")

            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

            snippet_parts = []
            if journal:
                snippet_parts.append(journal)
            if authors:
                snippet_parts.append(", ".join(authors))

            results.append(SearchResult(
                title=title,
                url=url,
                snippet=" | ".join(snippet_parts),
                source="pubmed.ncbi.nlm.nih.gov",
                rank=i,
                provider=self.name,
                published_date=pub_date or None,
                extra={
                    "pmid": pmid,
                    "journal": journal,
                    "authors": [a.get("name", "") for a in authors_raw],
                    "article_ids": item.get("articleids", []),
                },
            ))

        return ProviderResult(results=results)
