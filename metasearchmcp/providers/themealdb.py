"""TheMealDB recipe search via the keyless public API.

``GET https://www.themealdb.com/api/json/v1/1/search.php?s=QUERY`` returns
matching recipes from TheMealDB's community-maintained meal database as JSON.
No API key or authentication is required (the public demo key is used).

Each hit carries the recipe name, category, cuisine area, comma-separated
tags, a thumbnail, a YouTube tutorial link, and the ingredient/measure list.
``meals`` is ``null`` when nothing matches the query.

Note: the API is community-run and free; results are best-effort and the
search only matches against recipe names.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://www.themealdb.com/api/json/v1/1/search.php"
# TheMealDB returns at most this many meals per search request.
_MAX_API_RESULTS = 25
# The API exposes up to 20 numbered ingredient/measure pairs per meal.
_MAX_INGREDIENTS = 20
# Instructions are often several paragraphs; keep the snippet preview short.
_INSTRUCTIONS_PREVIEW = 200


class TheMealDBProvider(BaseProvider):
    """Search recipes on TheMealDB by name.

    Uses the keyless public API, which requires no authentication and returns
    structured recipe metadata: name, category, cuisine area, tags, thumbnail,
    YouTube tutorial, and the ingredient/measure list.
    """

    name = "themealdb"
    description = (
        "Search recipes by name — category, cuisine, ingredients, and "
        "instructions via the keyless TheMealDB API."
    )
    tags: ClassVar[list[str]] = ["food", "recipes", "media"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @classmethod
    def _ingredients(cls, meal: dict[str, Any]) -> list[str]:
        """Return ``"Measure Ingredient"`` pairs for a recipe, in order.

        Empty ingredient slots (e.g. ``strIngredient7`` with no value) are
        skipped so only real ingredients are reported.
        """
        ingredients: list[str] = []
        for index in range(1, _MAX_INGREDIENTS + 1):
            name = cls._clean_text(meal.get(f"strIngredient{index}"))
            if not name:
                continue
            measure = cls._clean_text(meal.get(f"strMeasure{index}"))
            ingredients.append(f"{measure} {name}".strip())
        return ingredients

    def _parse(self, data: Any) -> ProviderResult:
        """Parse the search.php response into structured search results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        meals = data.get("meals")
        if not isinstance(meals, list):
            return ProviderResult(results=results)

        for i, meal in enumerate(meals, start=1):
            if not isinstance(meal, dict):
                continue

            meal_id = meal.get("idMeal")
            title = self._clean_text(meal.get("strMeal"))
            if not meal_id or not title:
                continue

            category = self._clean_text(meal.get("strCategory"))
            area = self._clean_text(meal.get("strArea"))
            tags = [
                tag.strip()
                for tag in str(meal.get("strTags") or "").split(",")
                if tag.strip()
            ]
            ingredients = self._ingredients(meal)
            instructions = self._clean_text(meal.get("strInstructions"))

            snippet_parts: list[str] = []
            if instructions:
                snippet_parts.append(instructions[:_INSTRUCTIONS_PREVIEW])
            if category:
                snippet_parts.append(f"Category: {category}")
            if area:
                snippet_parts.append(f"Cuisine: {area}")
            if ingredients:
                snippet_parts.append(f"Ingredients: {', '.join(ingredients[:6])}")

            results.append(
                SearchResult(
                    title=title,
                    url=f"https://www.themealdb.com/meal/{meal_id}",
                    snippet=" | ".join(snippet_parts),
                    source="themealdb.com",
                    rank=i,
                    provider=self.name,
                    extra={
                        "meal_id": meal_id,
                        "category": category,
                        "area": area,
                        "tags": tags,
                        "ingredients": ingredients,
                        "thumbnail_url": str(meal.get("strMealThumb") or ""),
                        "youtube_url": str(meal.get("strYoutube") or ""),
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search TheMealDB for recipes matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(_API_URL, params={"s": query})
            resp.raise_for_status()
            data = resp.json()

        result = self._parse(data)
        # Truncate to the requested limit (the API may return up to 25 meals).
        result.results = result.results[:limit]
        return result
