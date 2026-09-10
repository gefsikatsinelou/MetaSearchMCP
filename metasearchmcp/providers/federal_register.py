"""U.S. Federal Register document search via the keyless public API.

The Federal Register (federalregister.gov) is the daily journal of the U.S.
federal government.  It publishes proposed rules, final rules, notices, and
presidential documents issued by every federal agency.  Its public API
requires no key or authentication:

``GET https://www.federalregister.gov/api/v1/documents.json?conditions[term]=QUERY``

``conditions[term]`` accepts free-text search terms.  Each document carries a
title, publication date, document type (Rule, Proposed Rule, Notice, or
Presidential Document), the issuing agencies, an abstract, a document number,
and a link to the record on federalregister.gov.  This makes the provider a
useful complement to CourtListener for regulatory, legal, and government-policy
research.  Parsing uses only the shared httpx client from the base provider.
"""

from __future__ import annotations

from typing import ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://www.federalregister.gov/api/v1/documents.json"
# The API permits up to 1000 results per page; we only need a handful.
_MAX_API_RESULTS = 20
# Restrict the (otherwise large) payload to just the fields we render.
_FIELDS = (
    "title",
    "html_url",
    "publication_date",
    "abstract",
    "type",
    "agencies",
    "document_number",
)


def _clean(value: object) -> str:
    """Collapse whitespace and control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


class FederalRegisterProvider(BaseProvider):
    """Search U.S. Federal Register documents via the keyless public API.

    Keyless.  Covers rules, proposed rules, notices, and presidential
    documents with titles, publication dates, document types, issuing
    agencies, abstracts, and links to the records on federalregister.gov.
    """

    name = "federal_register"
    description = (
        "Search U.S. Federal Register documents (agency rules, proposed "
        "rules, notices, presidential documents) via the public API, "
        "no key required."
    )
    tags: ClassVar[list[str]] = ["legal", "gov", "web"]

    @staticmethod
    def _agencies(value: object) -> list[str]:
        """Extract agency names from the document's agency list."""
        if not isinstance(value, list):
            return []
        names: list[str] = []
        for agency in value:
            if not isinstance(agency, dict):
                continue
            name = _clean(agency.get("name"))
            if name:
                names.append(name)
        return names

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a Federal Register documents response into results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        items = data.get("results")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in items:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue

            title = _clean(item.get("title"))
            url = _clean(item.get("html_url"))
            if not title or not url:
                continue

            abstract = _clean(item.get("abstract"))
            doc_type = _clean(item.get("type"))
            document_number = _clean(item.get("document_number"))
            agencies = self._agencies(item.get("agencies"))

            # Abstract first (most informative), then a metadata tail.
            tail_bits: list[str] = []
            if doc_type:
                tail_bits.append(doc_type)
            if agencies:
                tail_bits.append(f"Agencies: {', '.join(agencies[:4])}")
            snippet_parts = [abstract, " | ".join(tail_bits)]

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(p for p in snippet_parts if p)[
                        :MAX_SNIPPET_LENGTH
                    ],
                    source="federalregister.gov",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=self._iso_date_prefix(
                        item.get("publication_date")
                        if isinstance(item.get("publication_date"), str)
                        else None
                    ),
                    extra={
                        "document_number": document_number,
                        "type": doc_type,
                        "agencies": agencies,
                        "abstract": abstract,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the Federal Register for documents matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        qp = {
            "conditions[term]": query,
            "per_page": str(limit),
            "order": "relevance",
            "fields[]": list(_FIELDS),
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
