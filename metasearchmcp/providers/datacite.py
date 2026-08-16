"""DataCite research dataset search via the public, keyless REST API.

DataCite (datacite.org) issues persistent DOIs for research outputs and
aggregates metadata from hundreds of member repositories worldwide —
datasets, software, physical objects, and scholarly works. Its read-only
API requires no API key:

``GET https://api.datacite.org/dois?query=QUERY&page[size]=N``

Each hit exposes the DOI, title, creators, publisher, publication year,
abstract/description, and resource type. DataCite complements Zenodo by
covering non-Zenodo repositories (figshare, Dryad, institutional data
centres, and more) that register their DOIs through DataCite.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.datacite.org/dois"
# DataCite accepts larger page sizes, but 50 is plenty for one request.
_MAX_API_RESULTS = 50
# Links every DOI to its canonical landing page when the record has no URL.
_DOI_FALLBACK_PREFIX = "https://doi.org/"


class DataCiteProvider(BaseProvider):
    """Search research datasets and scholarly DOIs registered with DataCite.

    Uses the keyless public REST API, which aggregates metadata from member
    repositories across disciplines. Each hit carries the DOI, title,
    creators, publisher, publication year, abstract, and resource type.
    """

    name = "datacite"
    description = (
        "Search research datasets and scholarly works with DOIs registered "
        "via DataCite's member repositories, no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "data", "web"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _first_title(titles: object) -> str:
        """Return the first title from the DataCite titles list."""
        if not isinstance(titles, list):
            return ""
        for title in titles:
            if isinstance(title, dict) and title.get("title"):
                return DataCiteProvider._clean_text(title.get("title"))
        return ""

    @staticmethod
    def _creator_names(creators: object) -> list[str]:
        """Extract creator names from the DataCite creators list."""
        if not creators or not isinstance(creators, list):
            return []
        names: list[str] = []
        for creator in creators:
            if isinstance(creator, dict) and creator.get("name"):
                names.append(DataCiteProvider._clean_text(creator.get("name")))
        return names

    @staticmethod
    def _first_description(descriptions: object) -> str:
        """Return the longest abstract from the descriptions list."""
        if not isinstance(descriptions, list):
            return ""
        best = ""
        for description in descriptions:
            if isinstance(description, dict):
                text = DataCiteProvider._clean_text(description.get("description"))
                if len(text) > len(best):
                    best = text
        return best

    @staticmethod
    def _resource_type(types: object) -> str:
        """Return the human-readable resource type label."""
        if not isinstance(types, dict):
            return ""
        return DataCiteProvider._clean_text(
            types.get("resourceType") or types.get("resourceTypeGeneral")
        )

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the DataCite API response into structured search results."""
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

            title = self._first_title(attributes.get("titles"))
            doi = self._clean_text(attributes.get("doi"))
            if not title or not doi:
                continue

            landing_url = self._clean_text(attributes.get("url"))
            url = landing_url or f"{_DOI_FALLBACK_PREFIX}{doi}"

            creators = self._creator_names(attributes.get("creators"))
            publisher = self._clean_text(attributes.get("publisher"))
            year = attributes.get("publicationYear")
            year_text = self._clean_text(year) if year is not None else ""
            resource_type = self._resource_type(attributes.get("types"))
            abstract = self._first_description(attributes.get("descriptions"))

            snippet_parts: list[str] = []
            if abstract:
                snippet_parts.append(abstract[:MAX_SNIPPET_LENGTH])
            if resource_type:
                snippet_parts.append(f"Type: {resource_type}")
            if publisher:
                snippet_parts.append(f"Publisher: {publisher}")
            if creators:
                snippet_parts.append(f"Creators: {', '.join(creators[:5])}")

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(snippet_parts),
                    source="datacite.org",
                    rank=i,
                    provider=self.name,
                    published_date=year_text or None,
                    extra={
                        "doi": doi,
                        "creators": creators,
                        "publisher": publisher,
                        "resource_type": resource_type,
                        "year": year_text,
                        "abstract": abstract,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search DataCite for research datasets matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {"query": query, "page[size]": str(limit)}
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        result = self._parse(data)
        # Truncate defensively in case the API returns more than requested.
        result.results = result.results[:limit]
        return result
