"""Unit tests for the CoinGecko cryptocurrency search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.coingecko import CoinGeckoProvider

_SAMPLE_COIN = {
    "id": "bitcoin",
    "name": "Bitcoin",
    "symbol": "btc",
    "market_cap_rank": 1,
    "thumb": "https://coin-images.coingecko.com/coins/images/1/thumb/bitcoin.png",
    "large": "https://coin-images.coingecko.com/coins/images/1/large/bitcoin.png",
}

_SAMPLE_RESPONSE: dict[str, object] = {"coins": [_SAMPLE_COIN]}

_EMPTY_RESPONSE: dict[str, object] = {"coins": []}


def test_coingecko_parse_basic():
    p = CoinGeckoProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Bitcoin (BTC)"
    assert r.url == "https://www.coingecko.com/en/coins/bitcoin"
    assert "Symbol: BTC" in r.snippet
    assert "Market cap rank: #1" in r.snippet
    assert r.source == "coingecko.com"
    assert r.provider == "coingecko"
    assert r.rank == 1
    assert r.extra["coin_id"] == "bitcoin"
    assert r.extra["symbol"] == "BTC"
    assert r.extra["market_cap_rank"] == 1
    assert r.extra["thumbnail_url"].startswith("https://")
    assert r.extra["large_image_url"].startswith("https://")


def test_coingecko_parse_skips_coin_without_id_or_name():
    p = CoinGeckoProvider()
    result = p._parse({"coins": [{"name": "No Id"}, {"id": "1", "name": ""}]})
    assert result.results == []


def test_coingecko_parse_empty_coins():
    p = CoinGeckoProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_coingecko_parse_non_dict():
    p = CoinGeckoProvider()
    assert p._parse([{"name": "x"}]).results == []
    assert p._parse(None).results == []


def test_coingecko_parse_coins_not_a_list():
    p = CoinGeckoProvider()
    result = p._parse({"coins": {"name": "x"}})
    assert result.results == []


def test_coingecko_clean_text():
    assert CoinGeckoProvider._clean_text("  a\n  b  ") == "a b"
    assert CoinGeckoProvider._clean_text(None) == ""
    assert CoinGeckoProvider._clean_text("") == ""


def test_coingecko_is_available():
    """Keyless provider is always available."""
    assert CoinGeckoProvider().is_available() is True


@pytest.mark.asyncio
async def test_coingecko_search_hits_api_and_parses(respx_mock):
    """The search method hits the search endpoint and parses the response."""
    import respx

    respx_mock.get("https://api.coingecko.com/api/v3/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = CoinGeckoProvider()
    result = await p.search("bitcoin", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "coingecko"
    assert result.results[0].title == "Bitcoin (BTC)"


@pytest.mark.asyncio
async def test_coingecko_search_empty_response(respx_mock):
    """An empty coins list yields no results."""
    import respx

    respx_mock.get("https://api.coingecko.com/api/v3/search").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = CoinGeckoProvider()
    result = await p.search("zzz", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_coingecko_search_truncates_to_limit(respx_mock):
    """The search method truncates results to the requested limit."""
    import respx

    many_coins = {
        "coins": [
            {"id": f"coin-{i}", "name": f"Coin {i}", "symbol": f"C{i}"}
            for i in range(1, 6)
        ],
    }
    respx_mock.get("https://api.coingecko.com/api/v3/search").mock(
        return_value=respx.MockResponse(200, json=many_coins),
    )

    p = CoinGeckoProvider()
    result = await p.search("coin", SearchParams(num_results=2))

    assert len(result.results) == 2
    assert result.results[0].title == "Coin 1 (C1)"


@pytest.mark.asyncio
async def test_coingecko_search_passes_query_param(respx_mock):
    """The search method forwards the query as the query parameter."""
    import respx

    route = respx_mock.get("https://api.coingecko.com/api/v3/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = CoinGeckoProvider()
    await p.search("ethereum classic", SearchParams(num_results=3))

    request = route.calls.last.request
    assert request.url.params["query"] == "ethereum classic"
