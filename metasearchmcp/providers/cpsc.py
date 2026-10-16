"""Search U.S. consumer product recalls via the keyless CPSC API.

The U.S. Consumer Product Safety Commission (CPSC) publishes its recall
database through a public JSON web service that needs no API key::

    GET https://www.saferproducts.gov/RestWebServices/Recall?format=json&ProductName=stroller

The service returns a JSON array of recalls.  Each recall carries its
number, title, description, publication date, the affected products and
their category, the hazard, the remedy, the recalling firm and importer,
the country of manufacture, unit counts and product images.  The
``ProductName`` parameter matches the keyword against the recalled product
names; a blank or unmatched keyword yields an empty array.

Only the first product is used for the category and unit summary so the
normalized result stays compact, while the full recall remains reachable
through its canonical cpsc.gov URL.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_ENDPOINT = "https://www.saferproducts.gov/RestWebServices/Recall"
_SOURCE = "saferproducts.gov"
# Fallback landing page when a recall record carries no canonical URL.
_RECALL_URL = "https://www.cpsc.gov/Recalls"
# Keep the description preview short so the snippet stays readable.
_DESCRIPTION_PREVIEW = 300


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


class CpscProvider(BaseProvider):
    """Search U.S. Consumer Product Safety Commission product recalls.

    Keyless.  The query is a keyword matched against the names of recalled
    products; each match is returned with its recall number, hazard, recalling
    firm and canonical cpsc.gov URL.
    """

    name = "cpsc"
    description = (
        "Search U.S. Consumer Product Safety Commission (CPSC) recalls of "
        "consumer products (e.g. 'stroller', 'laminator' or 'bicycle'). Each "
        "result carries the recall title, number, hazard, firm, product "
        "category and a cpsc.gov link. No API key required."
    )
    tags: ClassVar[list[str]] = ["products", "gov", "us"]

    @staticmethod
    def _names(value: object) -> list[str]:
        """Return the non-empty ``Name`` strings from a list of objects."""
        if not isinstance(value, list):
            return []
        names: list[str] = []
        for entry in value:
            if not isinstance(entry, dict):
                continue
            name = _clean(entry.get("Name"))
            if name:
                names.append(name)
        return names

    @staticmethod
    def _countries(value: object) -> list[str]:
        """Return the non-empty ``Country`` strings from a list of objects."""
        if not isinstance(value, list):
            return []
        countries: list[str] = []
        for entry in value:
            if not isinstance(entry, dict):
                continue
            country = _clean(entry.get("Country"))
            if country:
                countries.append(country)
        return countries

    @staticmethod
    def _first_url(value: object) -> str:
        """Return the first non-empty ``URL`` from a list of objects."""
        if not isinstance(value, list):
            return ""
        for entry in value:
            if not isinstance(entry, dict):
                continue
            url = _clean(entry.get("URL"))
            if url:
                return url
        return ""

    @staticmethod
    def _first_product_field(value: object, field: str) -> str:
        """Return *field* from the first product object that defines it."""
        if not isinstance(value, list):
            return ""
        for entry in value:
            if not isinstance(entry, dict):
                continue
            found = _clean(entry.get(field))
            if found:
                return found
        return ""

    def _build_result(
        self,
        item: dict[str, Any],
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a single recall, or ``None``."""
        title = _clean(item.get("Title"))
        recall_number = _clean(item.get("RecallNumber"))
        if not title and not recall_number:
            return None

        description = _clean(item.get("Description"))
        products = self._names(item.get("Products"))
        category = self._first_product_field(item.get("Products"), "Type")
        units = self._first_product_field(item.get("Products"), "NumberOfUnits")
        hazards = self._names(item.get("Hazards"))
        firms = self._names(item.get("Manufacturers")) + self._names(
            item.get("Importers"),
        )
        countries = self._countries(item.get("ManufacturerCountries"))
        image = self._first_url(item.get("Images"))

        snippet_parts: list[str] = []
        if description:
            snippet_parts.append(description[:_DESCRIPTION_PREVIEW])
        if products:
            product_label = "; ".join(products)
            if category:
                product_label = f"{product_label} ({category})"
            snippet_parts.append(f"Products: {product_label}")
        if hazards:
            snippet_parts.append(f"Hazard: {hazards[0]}")
        snippet = " | ".join(snippet_parts)

        return SearchResult(
            title=title or f"CPSC recall {recall_number}",
            url=_clean(item.get("URL")) or _RECALL_URL,
            snippet=snippet[:MAX_SNIPPET_LENGTH],
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            published_date=self._iso_date_prefix(item.get("RecallDate")),
            extra={
                "recall_number": recall_number or None,
                "recall_id": item.get("RecallID"),
                "products": products,
                "category": category or None,
                "units": units or None,
                "hazards": hazards,
                "firm": firms[0] if firms else None,
                "countries": countries,
                "image": image or None,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a CPSC recall response into structured search results.

        The service's own ordering is preserved; records without a usable
        title or recall number are skipped and any other payload shape
        yields an empty page.
        """
        results: list[SearchResult] = []
        if not isinstance(data, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in data:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            built = self._build_result(item, len(results) + 1)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search CPSC recalls for products matching *query*.

        A blank query performs no request.  The keyword is matched against
        the recalled product names and the service's own order is kept.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results)
        async with self._client() as client:
            resp = await client.get(
                _ENDPOINT,
                params={
                    "format": "json",
                    "ProductName": cleaned,
                },
            )
            resp.raise_for_status()
            data: object = resp.json()

        return self._parse(data, limit)
