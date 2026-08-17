"""Zenodo research data search via the public, keyless REST API.

Zenodo (zenodo.org, by CERN) is an open-access repository for research
outputs — datasets, software, publications, theses, and other artefacts
deposited by researchers worldwide. Its read-only API requires no API key:

``GET https://zenodo.org/api/records?q=QUERY&size=N``

Each hit exposes the title, landing page, DOI, publication date, creators,
resource type, access right, and a free-text description. Zenodo complements
the other academic providers by covering datasets and software that are not
indexed as scholarly works by OpenAlex or Semantic Scholar.
"""

from __future__ import annotations

from typing import Any, ClassVar

from bs4 import BeautifulSoup

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://zenodo.org/api/records"
# Zenodo caps a single listing request at this many items.
_MAX_API_RESULTS = 100


class ZenodoProvider(BaseProvider):
    """Search open research data (datasets, software, publications) on Zenodo.

    Uses the keyless public REST API. Each result carries the record title,
    landing page URL, DOI, publication date, creators, resource type, and
    access right.
    """

    name = "zenodo"
    description = (
        "Search open research data — datasets, software, publications, and "
        "theses — deposited on Zenodo (CERN), no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "web"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _strip_html(value: object) -> str:
        """Strip HTML tags from a description and collapse whitespace."""
        if not value:
            return ""
        return " ".join(BeautifulSoup(str(value), "lxml").get_text(" ").split())

    @staticmethod
    def _creator_names(creators: object) -> list[str]:
        """Extract creator display names from the Zenodo creators list."""
        if not creators or not isinstance(creators, list):
            return []
        return [
            ZenodoProvider._clean_text(creator.get("name"))
            for creator in creators
            if isinstance(creator, dict) and creator.get("name")
        ]

    @staticmethod
    def _landing_url(hit: dict[str, Any]) -> str:
        """Return the best available landing page URL for a record."""
        links = hit.get("links")
        if isinstance(links, dict):
            for key in ("self_html", "self_doi_html"):
                url = links.get(key)
                if url:
                    return str(url)
        return ""

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the Zenodo API response into structured search results."""
        results: list[SearchResult] = []
        hits = data.get("hits") or {}
        items = hits.get("hits") or []

        for i, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") or {}
            title = self._clean_text(metadata.get("title"))
            url = self._landing_url(item)
            if not title or not url:
                continue

            doi = metadata.get("doi") or ""
            creators = self._creator_names(metadata.get("creators"))
            resource = metadata.get("resource_type") or {}
            resource_title = self._clean_text(resource.get("title"))
            access_right = self._clean_text(metadata.get("access_right"))
            license_info = metadata.get("license")
            license_id = (
                self._clean_text(license_info.get("id"))
                if isinstance(license_info, dict)
                else ""
            )
            keywords = [
                self._clean_text(kw)
                for kw in (metadata.get("keywords") or [])
                if self._clean_text(kw)
            ]

            snippet_parts: list[str] = []
            description = self._strip_html(metadata.get("description"))
            if description:
                snippet_parts.append(description[:MAX_SNIPPET_LENGTH])
            if creators:
                snippet_parts.append(f"Creators: {', '.join(creators[:5])}")
            if resource_title:
                snippet_parts.append(f"Type: {resource_title}")
            if access_right:
                snippet_parts.append(f"Access: {access_right}")

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(snippet_parts),
                    source="zenodo.org",
                    rank=i,
                    provider=self.name,
                    published_date=self._iso_date_prefix(
                        metadata.get("publication_date")
                    ),
                    extra={
                        "doi": doi,
                        "creators": creators,
                        "resource_type": resource_title,
                        "access_right": access_right,
                        "license": license_id,
                        "keywords": keywords,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Zenodo for research records matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {"q": query, "size": str(limit)}
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)
