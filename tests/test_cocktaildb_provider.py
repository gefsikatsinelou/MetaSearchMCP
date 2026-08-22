"""Unit tests for the TheCocktailDB cocktail search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.cocktaildb import CocktailDBProvider

_SAMPLE_DRINK = {
    "idDrink": "11007",
    "strDrink": "Margarita",
    "strCategory": "Ordinary Drink",
    "strAlcoholic": "Alcoholic",
    "strGlass": "Cocktail glass",
    "strTags": "IBA,ContemporaryClassic",
    "strDrinkThumb": "https://www.thecocktaildb.com/images/media/drink/wpxpvu1439905379.jpg",
    "strVideo": "https://www.youtube.com/watch?v=lVlQJ1MvS4g",
    "strInstructions": (
        "Rub the rim of the glass with the lime slice to make the salt stick "
        "to it. Shake the other ingredients with ice, then carefully pour."
    ),
    "strIngredient1": "Tequila",
    "strMeasure1": "1 1/2 oz ",
    "strIngredient2": "Triple sec",
    "strMeasure2": "1/2 oz ",
    "strIngredient3": "Lime juice",
    "strMeasure3": "1 oz ",
    "strIngredient4": "Salt",
    "strMeasure4": "",
    "strIngredient5": "",
    "strMeasure5": "",
}

_SAMPLE_RESPONSE: dict[str, object] = {"drinks": [_SAMPLE_DRINK]}

_EMPTY_RESPONSE: dict[str, object] = {"drinks": None}


def test_cocktaildb_parse_basic():
    p = CocktailDBProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Margarita"
    assert r.url == "https://www.thecocktaildb.com/drink/11007"
    assert "Category: Ordinary Drink" in r.snippet
    assert "Glass: Cocktail glass" in r.snippet
    assert "Alcoholic" in r.snippet
    expected_ingredients = (
        "Ingredients: 1 1/2 oz Tequila, 1/2 oz Triple sec, 1 oz Lime juice, Salt"
    )
    assert expected_ingredients in r.snippet
    assert r.source == "thecocktaildb.com"
    assert r.provider == "cocktaildb"
    assert r.rank == 1
    assert r.extra["drink_id"] == "11007"
    assert r.extra["tags"] == ["IBA", "ContemporaryClassic"]
    assert r.extra["ingredients"] == [
        "1 1/2 oz Tequila",
        "1/2 oz Triple sec",
        "1 oz Lime juice",
        "Salt",
    ]
    assert r.extra["thumbnail_url"].startswith("https://")
    assert r.extra["youtube_url"].startswith("https://www.youtube.com/")


def test_cocktaildb_parse_skips_drink_without_id_or_name():
    p = CocktailDBProvider()
    result = p._parse(
        {"drinks": [{"strDrink": "No Id"}, {"idDrink": "1", "strDrink": ""}]}
    )
    assert result.results == []


def test_cocktaildb_parse_empty_drinks_null():
    p = CocktailDBProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_cocktaildb_parse_non_dict():
    p = CocktailDBProvider()
    assert p._parse([{"strDrink": "x"}]).results == []
    assert p._parse(None).results == []


def test_cocktaildb_parse_drinks_not_a_list():
    p = CocktailDBProvider()
    result = p._parse({"drinks": {"strDrink": "x"}})
    assert result.results == []


def test_cocktaildb_ingredients_skips_empty_slots():
    ingredients = CocktailDBProvider._ingredients(_SAMPLE_DRINK)
    assert ingredients == [
        "1 1/2 oz Tequila",
        "1/2 oz Triple sec",
        "1 oz Lime juice",
        "Salt",
    ]


def test_cocktaildb_ingredients_no_measure():
    drink = {"strIngredient1": "sugar", "strMeasure1": "", "strIngredient2": ""}
    assert CocktailDBProvider._ingredients(drink) == ["sugar"]


def test_cocktaildb_clean_text():
    assert CocktailDBProvider._clean_text("  a\n  b  ") == "a b"
    assert CocktailDBProvider._clean_text(None) == ""
    assert CocktailDBProvider._clean_text("") == ""


def test_cocktaildb_is_available():
    """Keyless provider is always available."""
    assert CocktailDBProvider().is_available() is True


@pytest.mark.asyncio
async def test_cocktaildb_search_hits_api_and_parses(respx_mock):
    """The search method hits the search endpoint and parses the response."""
    import respx

    respx_mock.get("https://www.thecocktaildb.com/api/json/v1/1/search.php").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = CocktailDBProvider()
    result = await p.search("margarita", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "cocktaildb"
    assert result.results[0].title == "Margarita"


@pytest.mark.asyncio
async def test_cocktaildb_search_empty_response(respx_mock):
    """A null drinks list yields no results."""
    import respx

    respx_mock.get("https://www.thecocktaildb.com/api/json/v1/1/search.php").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = CocktailDBProvider()
    result = await p.search("zzz", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_cocktaildb_search_truncates_to_limit(respx_mock):
    """The search method truncates results to the requested limit."""
    import respx

    many_drinks = {
        "drinks": [
            {"idDrink": str(i), "strDrink": f"Drink {i}", "strInstructions": ""}
            for i in range(1, 6)
        ],
    }
    respx_mock.get("https://www.thecocktaildb.com/api/json/v1/1/search.php").mock(
        return_value=respx.MockResponse(200, json=many_drinks),
    )

    p = CocktailDBProvider()
    result = await p.search("drink", SearchParams(num_results=2))

    assert len(result.results) == 2
    assert result.results[0].title == "Drink 1"


@pytest.mark.asyncio
async def test_cocktaildb_search_passes_query_param(respx_mock):
    """The search method forwards the query as the s parameter."""
    import respx

    route = respx_mock.get(
        "https://www.thecocktaildb.com/api/json/v1/1/search.php"
    ).mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = CocktailDBProvider()
    await p.search("old fashioned", SearchParams(num_results=3))

    request = route.calls.last.request
    assert request.url.params["s"] == "old fashioned"
