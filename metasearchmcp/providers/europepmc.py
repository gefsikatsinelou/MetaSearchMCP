"""Europe PMC scholarly literature search via the public REST API.

Europe PMC (europepmc.org, EBI/EMBL) aggregates life-science literature
across PubMed, preprints (bioRxiv, medRxiv, arXiv), and other sources.
Its read-only search endpoint requires no API key:

``GET https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=QUERY&format=json&pageSize=N``

Each hit exposes the title, DOI, PMID, journal, authors, publication year,
and open-access flag. The provider is keyless and uses only the shared
httpx client from the base provider.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_MAX_API_RESULTS = 25


class EuropePmcProvider(BaseProvider):
    """Search life-science literature (PubMed, preprints) via Europe PMC.

    Keyless. Uses the public REST search API, which covers PubMed,
    bioRxiv, medRxiv, arXiv preprints and more. Each hit carries the
    title, landing page, DOI, journal, authors, publication year, and
    open-access flag.
    """

    name = "europepmc"
    description = (
        "Search life-science literature (PubMed, preprints) via Europe PMC, "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "web", "medical"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Europe PMC for *query* and return literature results."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        request_params = {
            "query": query,
            "format": "json",
            "pageSize": limit,
            "resultType": "lite",
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=request_params)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, max_results=limit)

    @staticmethod
    def _authors(item: dict[str, Any]) -> list[str]:
        """Split the authorString field into individual author names."""
        raw = (item.get("authorString") or "").strip()
        return [a.strip() for a in raw.split(",") if a.strip()]

    def _parse(
        self,
        data: dict[str, Any],
        max_results: int | None = None,
    ) -> ProviderResult:
        """Parse the Europe PMC JSON response into structured results."""
        results: list[SearchResult] = []
        limit = max_results or self._max_results
        items = (data.get("resultList") or {}).get("result") or []

        for item in items:
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "").strip()
            if not title:
                continue
            pmid = item.get("pmid") or ""
            doi = item.get("doi") or ""
            if pmid:
                url = f"https://europepmc.org/article/MED/{pmid}"
            elif doi:
                url = f"https://doi.org/{doi}"
            else:
                continue

            authors = self._authors(item)
            journal = (item.get("journalTitle") or "").strip()
            year = item.get("pubYear")
            year_str = str(year) if year else ""
            pub_date = year_str or self._iso_date_prefix(
                item.get("firstPublicationDate")
            )

            snippet_parts: list[str] = []
            if journal:
                snippet_parts.append(f"Journal: {journal}")
            if authors:
                snippet_parts.append(f"Authors: {', '.join(authors[:5])}")
            if year_str:
                snippet_parts.append(f"Year: {year_str}")
            if item.get("isOpenAccess") == "Y":
                snippet_parts.append("Open Access")

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(snippet_parts),
                    source="europepmc.org",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=pub_date,
                    extra={
                        "pmid": pmid,
                        "doi": doi,
                        "journal": journal,
                        "authors": authors,
                        "publication_year": year_str,
                        "open_access": item.get("isOpenAccess") == "Y",
                        "source_db": item.get("source") or "",
                    },
                ),
            )
            if len(results) >= limit:
                break

        return ProviderResult(results=results)
