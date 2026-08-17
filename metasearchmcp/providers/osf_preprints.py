"""OSF Preprints search via the keyless OSF API v2.

OSF Preprints (osf.io/preprints) aggregates preprints from a network of
partner preprint servers — PsyArXiv, SocArXiv, EarthArXiv, engrXiv,
MediArXiv, and hundreds of community-led servers — hosted on the Open
Science Framework. Its read-only API requires no API key:

``GET https://api.osf.io/v2/preprints/?filter[title]=QUERY&page[size]=N``

Each hit exposes the preprint title, abstract, DOI, publication date,
subject areas, and a canonical landing-page link. OSF complements
arXiv and PubMed by covering social-science, humanities, and
cross-domain preprints that those indexes do not.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.osf.io/v2/preprints"
# OSF accepts larger page sizes, but 50 is plenty for one request.
_MAX_API_RESULTS = 50


class OSFPreprintsProvider(BaseProvider):
    """Search preprints hosted on the Open Science Framework.

    Uses the keyless public API v2, which aggregates preprints from partner
    servers across disciplines. Each hit carries the title, abstract, DOI,
    publication date, subject areas, and a canonical landing-page link.
    """

    name = "osf_preprints"
    description = (
        "Search preprints from the Open Science Framework's network of "
        "partner preprint servers (PsyArXiv, SocArXiv, EarthArXiv, etc.), "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "web", "preprints"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _subject_names(subjects: object) -> list[str]:
        """Flatten the nested OSF subjects list into readable names."""
        if not isinstance(subjects, list):
            return []
        names: list[str] = []
        for level in subjects:
            if not isinstance(level, list):
                continue
            for subject in level:
                if isinstance(subject, dict) and subject.get("text"):
                    text = OSFPreprintsProvider._clean_text(subject.get("text"))
                    if text and text not in names:
                        names.append(text)
        return names

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the OSF API v2 response into structured search results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        items = data.get("data")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        for i, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            attributes = item.get("attributes")
            if not isinstance(attributes, dict):
                continue

            title = self._clean_text(attributes.get("title"))
            if not title:
                continue

            links = item.get("links")
            url = ""
            if isinstance(links, dict):
                url = self._clean_text(
                    links.get("html") or links.get("preprint_doi") or links.get("self")
                )

            doi = self._clean_text(attributes.get("doi"))
            abstract = self._clean_text(attributes.get("description"))
            subjects = self._subject_names(attributes.get("subjects"))
            published = self._clean_text(
                attributes.get("date_published")
                or attributes.get("original_publication_date")
            )
            citation = self._clean_text(attributes.get("custom_publication_citation"))

            snippet_parts: list[str] = []
            if abstract:
                snippet_parts.append(abstract[:MAX_SNIPPET_LENGTH])
            if citation:
                snippet_parts.append(f"Citation: {citation[:200]}")
            if subjects:
                snippet_parts.append(f"Subjects: {', '.join(subjects[:5])}")

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(snippet_parts),
                    source="osf.io",
                    rank=i,
                    provider=self.name,
                    published_date=self._iso_date_prefix(published),
                    extra={
                        "doi": doi,
                        "subjects": subjects,
                        "citation": citation,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search OSF Preprints for records matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {"filter[title]": query, "page[size]": str(limit)}
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        result = self._parse(data)
        # Truncate defensively in case the API returns more than requested.
        result.results = result.results[:limit]
        return result
