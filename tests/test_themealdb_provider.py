"""Unit tests for the TheMealDB recipe search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.themealdb import TheMealDBProvider

_SAMPLE_MEAL = {
    "idMeal": "52771",
    "strMeal": "Spicy Arrabiata Penne",
    "strCategory": "Vegetarian",
    "strArea": "Italian",
    "strTags": "Pasta,Curry",
    "strMealThumb": "https://www.themealdb.com/images/media/meals/ustsqw1468250014.jpg",
    "strYoutube": "https://www.youtube.com/watch?v=1IszT_guI08",
    "strInstructions": (
        "Bring a large pot of water to a boil. Add the penne and cook until "
        "al dente. Meanwhile, heat olive oil in a pan and fry the garlic."
    ),
    "strIngredient1": "penne rigate",
    "strMeasure1": "1 pound",
    "strIngredient2": "olive oil",
    "strMeasure2": "1/4 cup",
    "strIngredient3": "",
    "strMeasure3": "",
    "strIngredient4": "garlic",
    "strMeasure4": "3 cloves",
}

_SAMPLE_RESPONSE: dict[str, object] = {"meals": [_SAMPLE_MEAL]}

_EMPTY_RESPONSE: dict[str, object] = {"meals": None}


def test_themealdb_parse_basic():
    p = TheMealDBProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Spicy Arrabiata Penne"
    assert r.url == "https://www.themealdb.com/meal/52771"
    assert "Category: Vegetarian" in r.snippet
    assert "Cuisine: Italian" in r.snippet
    expected_ingredients = (
        "Ingredients: 1 pound penne rigate, 1/4 cup olive oil, 3 cloves garlic"
    )
    assert expected_ingredients in r.snippet
    assert r.source == "themealdb.com"
    assert r.provider == "themealdb"
    assert r.rank == 1
    assert r.extra["meal_id"] == "52771"
    assert r.extra["tags"] == ["Pasta", "Curry"]
    assert r.extra["ingredients"] == [
        "1 pound penne rigate",
        "1/4 cup olive oil",
        "3 cloves garlic",
    ]
    assert r.extra["thumbnail_url"].startswith("https://")
    assert r.extra["youtube_url"].startswith("https://www.youtube.com/")


def test_themealdb_parse_skips_meal_without_id_or_name():
    p = TheMealDBProvider()
    result = p._parse({"meals": [{"strMeal": "No Id"}, {"idMeal": "1", "strMeal": ""}]})
    assert result.results == []


def test_themealdb_parse_empty_meals_null():
    p = TheMealDBProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_themealdb_parse_non_dict():
    p = TheMealDBProvider()
    assert p._parse([{"strMeal": "x"}]).results == []
    assert p._parse(None).results == []


def test_themealdb_parse_meals_not_a_list():
    p = TheMealDBProvider()
    result = p._parse({"meals": {"strMeal": "x"}})
    assert result.results == []


def test_themealdb_ingredients_skips_empty_slots():
    ingredients = TheMealDBProvider._ingredients(_SAMPLE_MEAL)
    assert ingredients == [
        "1 pound penne rigate",
        "1/4 cup olive oil",
        "3 cloves garlic",
    ]


def test_themealdb_ingredients_no_measure():
    meal = {"strIngredient1": "salt", "strMeasure1": "", "strIngredient2": ""}
    assert TheMealDBProvider._ingredients(meal) == ["salt"]


def test_themealdb_clean_text():
    assert TheMealDBProvider._clean_text("  a\n  b  ") == "a b"
    assert TheMealDBProvider._clean_text(None) == ""
    assert TheMealDBProvider._clean_text("") == ""


def test_themealdb_is_available():
    """Keyless provider is always available."""
    assert TheMealDBProvider().is_available() is True


@pytest.mark.asyncio
async def test_themealdb_search_hits_api_and_parses(respx_mock):
    """The search method hits the search endpoint and parses the response."""
    import respx

    respx_mock.get("https://www.themealdb.com/api/json/v1/1/search.php").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = TheMealDBProvider()
    result = await p.search("arrabiata", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "themealdb"
    assert result.results[0].title == "Spicy Arrabiata Penne"


@pytest.mark.asyncio
async def test_themealdb_search_empty_response(respx_mock):
    """A null meals list yields no results."""
    import respx

    respx_mock.get("https://www.themealdb.com/api/json/v1/1/search.php").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = TheMealDBProvider()
    result = await p.search("zzz", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_themealdb_search_truncates_to_limit(respx_mock):
    """The search method truncates results to the requested limit."""
    import respx

    many_meals = {
        "meals": [
            {"idMeal": str(i), "strMeal": f"Meal {i}", "strInstructions": ""}
            for i in range(1, 6)
        ],
    }
    respx_mock.get("https://www.themealdb.com/api/json/v1/1/search.php").mock(
        return_value=respx.MockResponse(200, json=many_meals),
    )

    p = TheMealDBProvider()
    result = await p.search("meal", SearchParams(num_results=2))

    assert len(result.results) == 2
    assert result.results[0].title == "Meal 1"


@pytest.mark.asyncio
async def test_themealdb_search_passes_query_param(respx_mock):
    """The search method forwards the query as the s parameter."""
    import respx

    route = respx_mock.get("https://www.themealdb.com/api/json/v1/1/search.php").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = TheMealDBProvider()
    await p.search("chicken pie", SearchParams(num_results=3))

    request = route.calls.last.request
    assert request.url.params["s"] == "chicken pie"
