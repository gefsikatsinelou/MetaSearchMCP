"""OpenAlex scholarly works search via the public, keyless REST API.

OpenAlex (openalex.org, by OurResearch) indexes over 250 million scholarly
works — journal articles, preprints, conference papers, books, and datasets.
Its public API requires no API key for anonymous use:

``GET https://api.openalex.org/works?search=QUERY&per-page=N``

Each hit includes the title, landing-page URL, DOI, publication date, source
venue, authors, and citation count. Parsing uses only the shared httpx client
from the base provider.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://api.openalex.org/works"
# OpenAlex caps a single listing request at this many items.
_MAX_API_RESULTS = 50
# OpenAlex asks polite clients to identify themselves via a mailto param;
# a static public contact helps keep the anonymous tier stable.
_POLITE_MAILTO = "metasearchmcp@users.noreply.github.com"


class OpenAlexProvider(BaseProvider):
    """Search scholarly works across the OpenAlex catalog.

    Uses the keyless public REST API, which aggregates metadata from Crossref,
    PubMed, arXiv, and other scholarly indexes. Each hit carries the title,
    landing page, DOI, publication date, source venue, authors, and citation
    count.
    """

    name = "openalex"
    description = (
        "Search scholarly works (articles, preprints, books) via OpenAlex, "
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
    def _author_list(authorships: object) -> list[str]:
        """Extract author display names from the OpenAlex authorships list."""
        if not authorships or not isinstance(authorships, list):
            return []
        names: list[str] = []
        for authorship in authorships:
            if not isinstance(authorship, dict):
                continue
            author = authorship.get("author")
            if isinstance(author, dict) and author.get("display_name"):
                names.append(OpenAlexProvider._clean_text(author.get("display_name")))
        return names

    @staticmethod
    def _venue_label(location: object) -> str:
        """Return the source venue name from a work's primary location."""
        if not isinstance(location, dict):
            return ""
        source = location.get("source")
        if isinstance(source, dict):
            return OpenAlexProvider._clean_text(source.get("display_name"))
        return OpenAlexProvider._clean_text(location.get("raw_source_name"))

    @staticmethod
    def _landing_url(location: object, doi: object) -> str:
        """Return the best available landing page URL for a work."""
        if isinstance(location, dict):
            page_url = location.get("landing_page_url")
            if page_url:
                return str(page_url)
        if doi:
            return str(doi)
        return ""

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the OpenAlex API response into structured search results."""
        results: list[SearchResult] = []
        items = data.get("results") or []

        for i, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            title = self._clean_text(item.get("display_name"))
            doi = item.get("doi") or ""
            location = item.get("primary_location")
            url = self._landing_url(location, doi)
            if not title or not url:
                continue

            venue = self._venue_label(location)
            authors = self._author_list(item.get("authorships"))
            cited_by = item.get("cited_by_count") or 0
            work_type = self._clean_text(item.get("type"))
            language = self._clean_text(item.get("language"))

            snippet_parts: list[str] = []
            if authors:
                snippet_parts.append(f"Authors: {', '.join(authors[:5])}")
            if venue:
                snippet_parts.append(f"Venue: {venue}")
            if cited_by:
                snippet_parts.append(f"Cited by: {cited_by}")
            if work_type:
                snippet_parts.append(f"Type: {work_type}")

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(snippet_parts),
                    source="openalex.org",
                    rank=i,
                    provider=self.name,
                    published_date=self._iso_date_prefix(item.get("publication_date")),
                    extra={
                        "doi": doi,
                        "venue": venue,
                        "authors": authors,
                        "cited_by_count": int(cited_by) if cited_by else 0,
                        "work_type": work_type,
                        "language": language,
                        "open_access": bool(item.get("open_access", {}).get("is_oa"))
                        if isinstance(item.get("open_access"), dict)
                        else False,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search OpenAlex for scholarly works matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {
            "search": query,
            "per-page": str(limit),
            "mailto": _POLITE_MAILTO,
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)
