"""DOAJ open-access article search via the public, keyless REST API.

DOAJ (doaj.org, Directory of Open Access Journals) indexes peer-reviewed,
open-access scholarly articles across all disciplines. Its public API
requires no API key:

``GET https://doaj.org/api/search/articles/QUERY?pageSize=N``

Each hit includes the title, abstract, DOI, journal name, publication year,
and authors. Parsing uses only the shared httpx client from the base provider.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://doaj.org/api/search/articles"
# DOAJ caps a single listing request at this many items.
_MAX_API_RESULTS = 100


class DoajProvider(BaseProvider):
    """Search peer-reviewed open-access articles indexed by DOAJ.

    Uses the keyless public REST API, which aggregates metadata from journals
    across all disciplines. Each hit carries the title, abstract, DOI, journal
    name, publication year, and author list.
    """

    name = "doaj"
    description = (
        "Search peer-reviewed open-access scholarly articles indexed by DOAJ, "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "web"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _author_list(authors: object) -> list[str]:
        """Extract author names from the DOAJ author records."""
        if not isinstance(authors, list):
            return []
        return [
            DoajProvider._clean_text(author.get("name"))
            for author in authors
            if isinstance(author, dict) and author.get("name")
        ]

    @staticmethod
    def _doi(identifiers: object) -> str:
        """Return the DOI from the identifier list, if present."""
        if not isinstance(identifiers, list):
            return ""
        for item in identifiers:
            if isinstance(item, dict) and item.get("type") == "doi":
                return str(item.get("id") or "")
        return ""

    @staticmethod
    def _article_url(links: object, doi: str) -> str:
        """Return the best landing-page URL for an article."""
        if isinstance(links, list):
            for link in links:
                if isinstance(link, dict) and link.get("url"):
                    return str(link["url"])
        return f"https://doi.org/{doi}" if doi else ""

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the DOAJ API response into structured search results."""
        results: list[SearchResult] = []
        for i, item in enumerate(data.get("results") or [], start=1):
            if not isinstance(item, dict):
                continue
            bibjson = item.get("bibjson")
            if not isinstance(bibjson, dict):
                continue

            title = self._clean_text(bibjson.get("title"))
            if not title:
                continue
            doi = self._doi(bibjson.get("identifier"))
            url = self._article_url(bibjson.get("link"), doi)
            if not url:
                continue

            journal_data = bibjson.get("journal")
            journal = (
                self._clean_text(journal_data.get("title"))
                if isinstance(journal_data, dict)
                else ""
            )
            raw_year = bibjson.get("year")
            year = self._clean_text(raw_year) if raw_year is not None else ""
            authors = self._author_list(bibjson.get("author"))
            abstract = self._clean_text(bibjson.get("abstract"))

            snippet_parts: list[str] = []
            if journal:
                snippet_parts.append(f"Journal: {journal}")
            if year:
                snippet_parts.append(f"Year: {year}")
            if authors:
                snippet_parts.append(f"Authors: {', '.join(authors[:5])}")

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(snippet_parts),
                    source="doaj.org",
                    rank=i,
                    provider=self.name,
                    published_date=year or None,
                    extra={
                        "doi": doi,
                        "journal": journal,
                        "authors": authors,
                        "year": year,
                        "abstract": abstract,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search DOAJ for scholarly articles matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {"pageSize": str(limit)}
        async with self._client() as client:
            resp = await client.get(f"{_API_URL}/{quote(query)}", params=payload)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)
