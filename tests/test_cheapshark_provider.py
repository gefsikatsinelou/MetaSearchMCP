"""Unit tests for the CheapShark game-deal provider."""

from __future__ import annotations

import httpx
import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.cheapshark import CheapSharkProvider

_DEALS_URL = "https://www.cheapshark.com/api/1.0/deals"
_GAMES_URL = "https://www.cheapshark.com/api/1.0/games"
_STORES_URL = "https://www.cheapshark.com/api/1.0/stores"

_STORES_RESPONSE: list[dict[str, object]] = [
    {"storeID": "1", "storeName": "Steam", "isActive": 1},
    {"storeID": "7", "storeName": "GOG"},
    {"storeName": "No id"},
    "junk",
]

_DEALS_RESPONSE: list[object] = [
    {
        "internalName": "THEWITCHER3WILDHUNT",
        "title": "The Witcher 3: Wild Hunt",
        "dealID": "xp5saYR8o00pMpc%2Bb9jKjHOt69exT8tP%2BtvyFlH92g8%3D",
        "storeID": "7",
        "gameID": "112330",
        "salePrice": "7.99",
        "normalPrice": "39.99",
        "isOnSale": "1",
        "savings": "80.020005",
        "metacriticScore": "93",
        "steamRatingText": "Overwhelmingly Positive",
        "steamRatingPercent": "97",
        "steamAppID": "292030",
        "releaseDate": 1431993600,
        "dealRating": "9.8",
        "thumb": "https://cdn.example/thumb.jpg",
    },
    # Same game in another store -> deduplicated away.
    {
        "title": "The Witcher 3: Wild Hunt",
        "dealID": "other%3D",
        "storeID": "1",
        "gameID": "112330",
        "salePrice": "9.99",
        "savings": "75.0",
    },
    # Missing deal id -> skipped.
    {"title": "No Deal Id", "gameID": "999", "storeID": "1"},
    # Second distinct game with a minimal payload.
    {
        "title": "Cyberpunk 2077",
        "dealID": "abc%3D",
        "gameID": "216307",
        "storeID": "1",
    },
    "junk",
    None,
]

_GAMES_RESPONSE: list[object] = [
    {
        "gameID": "316791",
        "steamAppID": "1651600",
        "cheapest": "4.79",
        "cheapestDealID": "55V6eHFbNqry9LhlBbLK%2FIBym47nRfZ5dEQd4pEzQ1U%3D",
        "external": "Reigns: The Witcher",
        "internalName": "REIGNSTHEWITCHER",
        "thumb": "https://cdn.example/reigns.jpg",
    },
    {
        # No cheapest deal -> falls back to a game-id redirect URL.
        "gameID": "112330",
        "steamAppID": None,
        "external": "The Witcher 3: Wild Hunt",
    },
    "junk",
    {"gameID": "", "external": "Nameless"},
]


@pytest.fixture(autouse=True)
def _clear_store_cache():
    """Reset the process-wide store-name cache between tests."""
    CheapSharkProvider._store_cache = {}
    yield
    CheapSharkProvider._store_cache = {}


def _provider() -> CheapSharkProvider:
    return CheapSharkProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "cheapshark"
    assert p.tags == ["shopping", "deals", "games", "web"]
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "cheapshark" in registry
    assert registry["cheapshark"].tags == ["shopping", "deals", "games", "web"]


def test_parse_stores_indexes_ids() -> None:
    assert CheapSharkProvider._parse_stores(_STORES_RESPONSE) == {
        "1": "Steam",
        "7": "GOG",
    }
    assert CheapSharkProvider._parse_stores({}) == {}
    assert CheapSharkProvider._parse_stores("junk") == {}


def test_iso_date_conversions() -> None:
    assert CheapSharkProvider._iso_date(1431993600) == "2015-05-19"
    assert CheapSharkProvider._iso_date("1431993600") == "2015-05-19"
    assert CheapSharkProvider._iso_date(0) is None
    assert CheapSharkProvider._iso_date(None) is None
    assert CheapSharkProvider._iso_date("not-a-date") is None


def test_parse_deals_dedupes_games_and_builds_result() -> None:
    stores = CheapSharkProvider._parse_stores(_STORES_RESPONSE)
    result = _provider()._parse_deals(_DEALS_RESPONSE, stores, limit=10)

    assert [r.title for r in result.results] == [
        "The Witcher 3: Wild Hunt",
        "Cyberpunk 2077",
    ]
    first = result.results[0]
    assert first.url.startswith("https://www.cheapshark.com/redirect?dealID=")
    assert first.url.endswith("H92g8%3D")
    assert first.source == "cheapshark.com"
    assert first.provider == "cheapshark"
    assert first.rank == 1
    assert first.published_date == "2015-05-19"
    assert "On sale: $7.99 (was $39.99, 80% off)" in first.snippet
    assert "at GOG" in first.snippet
    assert "Metacritic 93" in first.snippet
    assert "Steam: Overwhelmingly Positive (97%)" in first.snippet
    assert first.extra["store"] == "GOG"
    assert first.extra["sale_price"] == 7.99
    assert first.extra["normal_price"] == 39.99
    assert first.extra["savings_percent"] == 80.02
    assert first.extra["steam_app_id"] == "292030"
    assert first.extra["metacritic_score"] == 93
    assert first.extra["is_on_sale"] is True

    second = result.results[1]
    assert second.rank == 2
    assert second.snippet == "at Steam"
    assert second.published_date is None
    assert second.extra["store"] == "Steam"
    assert second.extra["sale_price"] is None


def test_parse_deals_handles_empty_and_unknown_store() -> None:
    assert _provider()._parse_deals([], {}, limit=5).results == []
    assert _provider()._parse_deals("junk", {}, limit=5).results == []

    result = _provider()._parse_deals(
        [{"title": "Mystery", "dealID": "x%3D", "gameID": "1", "storeID": "42"}],
        {},
        limit=5,
    )
    assert result.results[0].extra["store"] == "42"


def test_parse_deals_respects_limit() -> None:
    stores = CheapSharkProvider._parse_stores(_STORES_RESPONSE)
    result = _provider()._parse_deals(_DEALS_RESPONSE, stores, limit=1)
    assert len(result.results) == 1
    assert result.results[0].title == "The Witcher 3: Wild Hunt"


def test_parse_games_fallback() -> None:
    result = _provider()._parse_games(_GAMES_RESPONSE, limit=10)

    assert [r.title for r in result.results] == [
        "Reigns: The Witcher",
        "The Witcher 3: Wild Hunt",
    ]
    first = result.results[0]
    assert first.snippet == "Cheapest tracked price: $4.79"
    assert first.url.endswith("EzQ1U%3D")
    assert first.extra["cheapest_price"] == 4.79
    assert first.extra["internal_name"] == "REIGNSTHEWITCHER"

    second = result.results[1]
    assert second.url == "https://www.cheapshark.com/redirect?gameID=112330"
    assert second.snippet == ""
    assert second.rank == 2
    assert second.extra["steam_app_id"] is None

    assert _provider()._parse_games([], limit=5).results == []
    assert _provider()._parse_games("junk", limit=5).results == []


@pytest.mark.asyncio
async def test_search_returns_deals_and_caches_stores(respx_mock) -> None:
    import respx

    stores_route = respx_mock.get(_STORES_URL).mock(
        return_value=respx.MockResponse(200, json=_STORES_RESPONSE),
    )
    deals_route = respx_mock.get(_DEALS_URL).mock(
        return_value=respx.MockResponse(200, json=_DEALS_RESPONSE),
    )

    provider = _provider()
    result = await provider.search("witcher", SearchParams(num_results=5))

    assert [r.title for r in result.results] == [
        "The Witcher 3: Wild Hunt",
        "Cyberpunk 2077",
    ]
    assert result.results[0].extra["store"] == "GOG"
    assert stores_route.call_count == 1
    assert deals_route.called
    params = deals_route.calls[0].request.url.params
    assert params["title"] == "witcher"
    assert params["onSale"] == "1"
    assert params["pageSize"] == "15"

    # The store map is cached: a second search must not refetch it.
    result = await provider.search("cyberpunk", SearchParams(num_results=5))
    assert result.results
    assert stores_route.call_count == 1
    assert deals_route.call_count == 2


@pytest.mark.asyncio
async def test_search_falls_back_to_games_catalogue(respx_mock) -> None:
    import respx

    respx_mock.get(_STORES_URL).mock(
        return_value=respx.MockResponse(200, json=_STORES_RESPONSE),
    )
    respx_mock.get(_DEALS_URL).mock(
        return_value=respx.MockResponse(200, json=[]),
    )
    games_route = respx_mock.get(_GAMES_URL).mock(
        return_value=respx.MockResponse(200, json=_GAMES_RESPONSE),
    )

    result = await _provider().search("witcher", SearchParams(num_results=4))

    assert [r.title for r in result.results] == [
        "Reigns: The Witcher",
        "The Witcher 3: Wild Hunt",
    ]
    assert games_route.called
    assert games_route.calls[0].request.url.params["limit"] == "4"


@pytest.mark.asyncio
async def test_search_tolerates_store_lookup_failure(respx_mock) -> None:
    import respx

    respx_mock.get(_STORES_URL).mock(side_effect=httpx.ConnectError("boom"))
    respx_mock.get(_DEALS_URL).mock(
        return_value=respx.MockResponse(200, json=_DEALS_RESPONSE),
    )

    result = await _provider().search("witcher", SearchParams(num_results=5))

    assert result.results
    # Without store names the raw store id is still reported.
    assert result.results[0].extra["store"] == "7"
    assert "at 7" in result.results[0].snippet


@pytest.mark.asyncio
async def test_search_with_blank_query_returns_empty(respx_mock) -> None:
    import respx

    deals_route = respx_mock.get(_DEALS_URL).mock(
        return_value=respx.MockResponse(200, json=_DEALS_RESPONSE),
    )

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not deals_route.called
