"""Open Food Facts product search via the keyless public API.

``GET https://world.openfoodfacts.org/cgi/search.pl`` returns matching
food products from the Open Food Facts database as JSON. No API key or
authentication is required, and the project data is released under the
ODbL open database license.

The search endpoint returns rich product metadata directly (name, brand,
ingredients, Nutri-Score, NOVA group, allergens, and images), so no
per-product follow-up fetches are needed. Each result links to the
product page on openfoodfacts.org.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://world.openfoodfacts.org/cgi/search.pl"
# The OFF search API caps page size at 100 items per request.
_MAX_API_RESULTS = 50
# The OFF API sorts by relevance when this field is omitted.
_SEARCH_FIELDS = (
    "code,product_name,brands,quantity,categories,ingredients_text,"
    "allergens,nutriscore_grade,nova_group,image_front_url,url"
)


class OpenFoodFactsProvider(BaseProvider):
    """Search food products in the Open Food Facts database.

    Uses the keyless public API, which requires no authentication and
    returns structured product metadata: name, brand, ingredients,
    Nutri-Score, NOVA group, allergens, and a front image.
    """

    name = "openfoodfacts"
    description = (
        "Search the Open Food Facts open food database — product name, "
        "brand, ingredients, Nutri-Score, and NOVA group via the keyless API."
    )
    tags: ClassVar[list[str]] = ["food", "products", "web"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    def _parse(self, data: Any, limit: int | None = None) -> ProviderResult:
        """Parse the /search.pl response into structured results."""
        results: list[SearchResult] = []
        max_results = limit or self._max_results
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        products = data.get("products")
        if not isinstance(products, list):
            return ProviderResult(results=results)

        for i, item in enumerate(products, start=1):
            if i > max_results:
                break
            if not isinstance(item, dict):
                continue

            title = self._clean(item.get("product_name"))
            if not title:
                continue

            brand = self._clean(item.get("brands"))
            quantity = self._clean(item.get("quantity"))
            ingredients = self._clean(item.get("ingredients_text"))
            allergens = self._clean(item.get("allergens"))
            categories = self._clean(item.get("categories"))
            nutriscore = self._clean(item.get("nutriscore_grade"))
            nova = item.get("nova_group")

            snippet_parts: list[str] = []
            if brand:
                snippet_parts.append(brand)
            if quantity:
                snippet_parts.append(quantity)
            if categories:
                snippet_parts.append(categories)
            if ingredients:
                snippet_parts.append(f"Ingredients: {ingredients[:180]}")

            results.append(
                SearchResult(
                    title=title,
                    url=str(item.get("url") or ""),
                    snippet=" | ".join(snippet_parts),
                    source="openfoodfacts.org",
                    rank=i,
                    provider=self.name,
                    extra={
                        "brand": brand,
                        "quantity": quantity,
                        "categories": categories,
                        "ingredients": ingredients,
                        "allergens": allergens,
                        "nutriscore_grade": nutriscore,
                        "nova_group": str(nova) if nova is not None else "",
                        "image_url": str(item.get("image_front_url") or ""),
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the Open Food Facts database for products matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={
                    "search_terms": query,
                    "search_simple": "1",
                    "action": "process",
                    "json": "1",
                    "page_size": str(limit),
                    "fields": _SEARCH_FIELDS,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit)
