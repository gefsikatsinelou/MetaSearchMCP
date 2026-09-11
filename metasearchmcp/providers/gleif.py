"""Global Legal Entity Identifier (LEI) search via the keyless GLEIF API.

The Global Legal Entity Identifier Foundation (GLEIF) maintains the global
registry of Legal Entity Identifiers — 20-character codes that uniquely
identify legal entities taking part in financial transactions.  Its public
API requires no key or authentication:

``GET https://api.gleif.org/api/v1/lei-records?filter[entity.legalName]=QUERY``

The ``filter[entity.legalName]`` parameter performs a case-insensitive
substring match on the registered legal name.  Each record carries the LEI,
the legal name, the entity status (ACTIVE / INACTIVE), the jurisdiction,
the legal form, the legal address, and registration metadata.  This makes
the provider a useful complement to SEC EDGAR and Yahoo Finance for company,
counterparty, and due-diligence research.  Parsing uses only the shared
httpx client from the base provider.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.gleif.org/api/v1/lei-records"
# The API caps page[size] at 200; we only need a handful of records.
_MAX_API_RESULTS = 25
_RECORD_URL = "https://search.gleif.org/#/record/{lei}"


def _clean(value: object) -> str:
    """Collapse whitespace and control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


class GleifProvider(BaseProvider):
    """Search the global Legal Entity Identifier registry via GLEIF.

    Keyless.  Covers legal entities worldwide with their LEI code, legal
    name, entity status, jurisdiction, legal form, and legal address.
    """

    name = "gleif"
    description = (
        "Search the global Legal Entity Identifier (LEI) registry for "
        "companies and legal entities (legal name, jurisdiction, status) "
        "via the public GLEIF API, no key required."
    )
    tags: ClassVar[list[str]] = ["finance", "legal", "business", "web", "reference"]

    @staticmethod
    def _address(entity: dict[str, Any]) -> tuple[str, str]:
        """Return the legal address city and ISO country code, if present."""
        address = entity.get("legalAddress")
        if not isinstance(address, dict):
            return "", ""
        city = _clean(address.get("city"))
        country = _clean(address.get("country"))
        return city, country

    @staticmethod
    def _legal_name(entity: dict[str, Any]) -> str:
        """Extract the registered legal name from an entity record."""
        legal_name = entity.get("legalName")
        if isinstance(legal_name, dict):
            return _clean(legal_name.get("name"))
        return _clean(legal_name)

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a GLEIF LEI-records response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        items = data.get("data")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in items:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            attributes = item.get("attributes")
            if not isinstance(attributes, dict):
                continue

            lei = _clean(attributes.get("lei")) or _clean(item.get("id"))
            entity = attributes.get("entity")
            if not isinstance(entity, dict):
                continue
            legal_name = self._legal_name(entity)
            if not lei or not legal_name:
                continue

            status = _clean(entity.get("status"))
            jurisdiction = _clean(entity.get("jurisdiction"))
            category = _clean(entity.get("category"))
            city, country = self._address(entity)
            legal_form = entity.get("legalForm")
            form_id = (
                _clean(legal_form.get("id")) if isinstance(legal_form, dict) else ""
            )

            # Status first (most actionable), then jurisdiction/address.
            tail_bits: list[str] = []
            if status:
                tail_bits.append(f"Status: {status}")
            if jurisdiction:
                tail_bits.append(f"Jurisdiction: {jurisdiction}")
            if category:
                tail_bits.append(f"Category: {category}")
            if form_id:
                tail_bits.append(f"Legal form: {form_id}")
            location = ", ".join(part for part in (city, country) if part)
            if location:
                tail_bits.append(f"Address: {location}")
            tail_bits.append(f"LEI: {lei}")

            results.append(
                SearchResult(
                    title=legal_name,
                    url=_RECORD_URL.format(lei=lei),
                    snippet=" | ".join(tail_bits)[:MAX_SNIPPET_LENGTH],
                    source="gleif.org",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=self._iso_date_prefix(
                        entity.get("creationDate")
                        if isinstance(entity.get("creationDate"), str)
                        else None
                    ),
                    extra={
                        "lei": lei,
                        "status": status,
                        "jurisdiction": jurisdiction,
                        "country": country,
                        "category": category,
                        "legal_form": form_id,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the GLEIF registry for entities matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        qp = {
            "filter[entity.legalName]": query,
            "page[size]": str(limit),
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
