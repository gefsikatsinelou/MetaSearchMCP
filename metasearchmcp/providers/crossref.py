"""CrossRef scholarly metadata search via the public REST API."""

from __future__ import annotations

import re

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://api.crossref.org/works"
_MAX_DISPLAY_AUTHORS = 3


class CrossrefProvider(BaseProvider):
    """CrossRef scholarly metadata search via the public REST API.

    Covers 145M+ DOI-registered scholarly works (papers, books, datasets).
    No authentication required.
    Include a mailto in requests for polite pool access (faster, no rate limit).
    """

    name = "crossref"
    description = (
        "Search scholarly metadata from Crossref covering "
        "journals, books, and conference papers."
    )
    tags = ["academic", "web"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        qp = {
            "query": query,
            "rows": min(params.num_results, self._max_results, 20),
            "select": (
                "DOI,title,abstract,author,container-title,"
                "published,URL,is-referenced-by-count,type"
            ),
            "mailto": "metasearchmcp@example.com",  # polite pool
        }

        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []
        items = data.get("message", {}).get("items", [])

        for i, item in enumerate(items, start=1):
            titles = item.get("title", [])
            title = titles[0] if titles else ""

            doi = item.get("DOI", "")
            url = item.get("URL", "") or (f"https://doi.org/{doi}" if doi else "")

            abstract = (item.get("abstract") or "")[:400]
            # CrossRef abstracts sometimes include JATS XML tags
            abstract = re.sub(r"<[^>]+>", "", abstract).strip()

            authors_raw = item.get("author", [])
            authors = [
                f"{a.get('given', '')} {a.get('family', '')}".strip()
                for a in authors_raw[:_MAX_DISPLAY_AUTHORS]
            ]
            if len(authors_raw) > _MAX_DISPLAY_AUTHORS:
                authors.append("et al.")

            container = (item.get("container-title") or [""])[0]
            citations = item.get("is-referenced-by-count", 0)
            doc_type = item.get("type", "")

            published_parts = item.get("published", {}).get("date-parts", [[]])
            published = ""
            if published_parts and published_parts[0]:
                parts = published_parts[0]
                published = "-".join(str(p).zfill(2) for p in parts)[:10]

            snippet_parts = [abstract]
            if container:
                snippet_parts.append(container)
            if authors:
                snippet_parts.append(", ".join(authors))
            if citations:
                snippet_parts.append(f"Cited by: {citations}")

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(p for p in snippet_parts if p),
                    source="crossref.org",
                    rank=i,
                    provider=self.name,
                    published_date=published or None,
                    extra={
                        "doi": doi,
                        "type": doc_type,
                        "citation_count": citations,
                        "authors": [
                            f"{a.get('given', '')} {a.get('family', '')}".strip()
                            for a in authors_raw
                        ],
                        "container_title": container,
                    },
                ),
            )

        return ProviderResult(results=results)
