"""Unit tests for the Open Food Facts product search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.openfoodfacts import OpenFoodFactsProvider

_SAMPLE_ITEM = {
    "code": "3017620422003",
    "product_name": "Nutella",
    "brands": "Nutella, Ferrero",
    "quantity": "750 g",
    "categories": "en:Confectionary based spreads, en:Pâtes à tartiner",
    "ingredients_text": "Sucre, huile de palme, NOISETTES 13%",
    "allergens": "lait, fruits à coque, soja",
    "nutriscore_grade": "e",
    "nova_group": 4,
    "image_front_url": "https://images.openfoodfacts.org/images/products/front.jpg",
    "url": "https://world.openfoodfacts.org/product/3017620422003/nutella",
}

_SAMPLE_RESPONSE: dict[str, object] = {
    "count": 1028,
    "page": 1,
    "page_count": 514,
    "products": [
        _SAMPLE_ITEM,
        {
            "code": "7622210449283",
            "product_name": "Chocolate Biscuits",
            "brands": "LU",
            "quantity": "300 g",
            "categories": "en:Biscuits",
            "ingredients_text": "Farine de blé, sucre",
            "allergens": "gluten, lait",
            "nutriscore_grade": "d",
            "nova_group": 3,
            "image_front_url": "",
            "url": "https://world.openfoodfacts.org/product/7622210449283",
        },
        {
            # Missing product_name -> skipped.
            "code": "0000000000000",
            "brands": "Unknown",
        },
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"count": 0, "products": []}


def _provider() -> OpenFoodFactsProvider:
    return OpenFoodFactsProvider()


def test_off_name_and_tags() -> None:
    p = _provider()
    assert p.name == "openfoodfacts"
    assert p.tags == ["food", "products", "web"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Nutella"
    assert r.url == "https://world.openfoodfacts.org/product/3017620422003/nutella"
    assert "Nutella, Ferrero" in r.snippet
    assert "750 g" in r.snippet
    assert "Ingredients: Sucre, huile de palme, NOISETTES 13%" in r.snippet
    assert r.provider == "openfoodfacts"
    assert r.source == "openfoodfacts.org"
    assert r.rank == 1
    assert r.extra["brand"] == "Nutella, Ferrero"
    assert r.extra["quantity"] == "750 g"
    assert r.extra["nutriscore_grade"] == "e"
    assert r.extra["nova_group"] == "4"
    assert r.extra["allergens"] == "lait, fruits à coque, soja"
    assert r.extra["image_url"].startswith("https://images.openfoodfacts.org")


def test_parse_skips_items_missing_name() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert all(r.title for r in result.results)
    assert all(r.url for r in result.results)


def test_parse_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1
    assert result.results[0].title == "Nutella"


def test_parse_empty_and_malformed() -> None:
    assert _provider()._parse(_EMPTY_RESPONSE).results == []
    assert _provider()._parse({}).results == []
    assert _provider()._parse({"products": ["not-a-dict", None, 42]}).results == []
    assert _provider()._parse("junk").results == []


def test_clean_text() -> None:
    assert OpenFoodFactsProvider._clean("  a\n  b\t ") == "a b"
    assert OpenFoodFactsProvider._clean(None) == ""
    assert OpenFoodFactsProvider._clean("") == ""


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get("https://world.openfoodfacts.org/cgi/search.pl").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("nutella", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "openfoodfacts"
    request = respx_mock.calls.last.request
    assert request.url.params["search_terms"] == "nutella"
    assert request.url.params["page_size"] == "5"
    assert request.url.params["json"] == "1"


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://world.openfoodfacts.org/cgi/search.pl").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("zzz", SearchParams(num_results=5))
    assert result.results == []
