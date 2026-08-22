"""TheCocktailDB cocktail search via the keyless public API.

``GET https://www.thecocktaildb.com/api/json/v1/1/search.php?s=QUERY`` returns
matching drinks from TheCocktailDB's community-maintained cocktail database as
JSON. No API key or authentication is required (the public demo key is used).

Each hit carries the drink name, category, alcohol classification, glass type,
IBA designation, comma-separated tags, a thumbnail, a YouTube tutorial link,
and the ingredient/measure list. ``drinks`` is ``null`` when nothing matches
the query.

Note: the API is community-run and free; results are best-effort and the
search only matches against drink names.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://www.thecocktaildb.com/api/json/v1/1/search.php"
# TheCocktailDB returns at most this many drinks per search request.
_MAX_API_RESULTS = 25
# The API exposes up to 15 numbered ingredient/measure pairs per drink.
_MAX_INGREDIENTS = 15
# Instructions are often several paragraphs; keep the snippet preview short.
_INSTRUCTIONS_PREVIEW = 200


class CocktailDBProvider(BaseProvider):
    """Search cocktails and drinks on TheCocktailDB by name.

    Uses the keyless public API, which requires no authentication and returns
    structured drink metadata: name, category, alcoholic classification, glass
    type, tags, thumbnail, YouTube tutorial, and the ingredient/measure list.
    """

    name = "cocktaildb"
    description = (
        "Search cocktails and drinks by name — category, glass, ingredients, "
        "and instructions via the keyless TheCocktailDB API."
    )
    tags: ClassVar[list[str]] = ["food", "drinks", "media"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @classmethod
    def _ingredients(cls, drink: dict[str, Any]) -> list[str]:
        """Return ``"Measure Ingredient"`` pairs for a drink, in order.

        Empty ingredient slots (e.g. ``strIngredient7`` with no value) are
        skipped so only real ingredients are reported.
        """
        ingredients: list[str] = []
        for index in range(1, _MAX_INGREDIENTS + 1):
            name = cls._clean_text(drink.get(f"strIngredient{index}"))
            if not name:
                continue
            measure = cls._clean_text(drink.get(f"strMeasure{index}"))
            ingredients.append(f"{measure} {name}".strip())
        return ingredients

    def _parse(self, data: Any) -> ProviderResult:
        """Parse the search.php response into structured search results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        drinks = data.get("drinks")
        if not isinstance(drinks, list):
            return ProviderResult(results=results)

        for i, drink in enumerate(drinks, start=1):
            if not isinstance(drink, dict):
                continue

            drink_id = drink.get("idDrink")
            title = self._clean_text(drink.get("strDrink"))
            if not drink_id or not title:
                continue

            category = self._clean_text(drink.get("strCategory"))
            glass = self._clean_text(drink.get("strGlass"))
            alcoholic = self._clean_text(drink.get("strAlcoholic"))
            tags = [
                tag.strip()
                for tag in str(drink.get("strTags") or "").split(",")
                if tag.strip()
            ]
            ingredients = self._ingredients(drink)
            instructions = self._clean_text(drink.get("strInstructions"))

            snippet_parts: list[str] = []
            if instructions:
                snippet_parts.append(instructions[:_INSTRUCTIONS_PREVIEW])
            if category:
                snippet_parts.append(f"Category: {category}")
            if glass:
                snippet_parts.append(f"Glass: {glass}")
            if alcoholic:
                snippet_parts.append(alcoholic)
            if ingredients:
                snippet_parts.append(f"Ingredients: {', '.join(ingredients[:6])}")

            results.append(
                SearchResult(
                    title=title,
                    url=f"https://www.thecocktaildb.com/drink/{drink_id}",
                    snippet=" | ".join(snippet_parts),
                    source="thecocktaildb.com",
                    rank=i,
                    provider=self.name,
                    extra={
                        "drink_id": drink_id,
                        "category": category,
                        "glass": glass,
                        "alcoholic": alcoholic,
                        "tags": tags,
                        "ingredients": ingredients,
                        "thumbnail_url": str(drink.get("strDrinkThumb") or ""),
                        "youtube_url": str(drink.get("strVideo") or ""),
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search TheCocktailDB for drinks matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(_API_URL, params={"s": query})
            resp.raise_for_status()
            data = resp.json()

        result = self._parse(data)
        # Truncate to the requested limit (the API may return up to 25 drinks).
        result.results = result.results[:limit]
        return result
