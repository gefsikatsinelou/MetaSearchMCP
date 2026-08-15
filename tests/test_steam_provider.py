"""Unit tests for the Steam Store game search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.steam import SteamProvider

_SAMPLE_RESPONSE = {
    "total": 3,
    "items": [
        {
            "type": "app",
            "name": "Portal 2",
            "id": 620,
            "price": {"currency": "USD", "initial": 999, "final": 999},
            "tiny_image": "https://cdn.example.com/apps/620/capsule.jpg",
            "metascore": "95",
            "platforms": {"windows": True, "mac": False, "linux": True},
            "streamingvideo": False,
            "controller_support": "full",
        },
        {
            "type": "app",
            "name": "Free Game",
            "id": 999,
            "price": {"currency": "USD", "initial": 0, "final": 0},
            "tiny_image": "",
            "metascore": "",
            "platforms": {"windows": True, "mac": True, "linux": True},
            "streamingvideo": False,
        },
        {
            "type": "app",
            "name": "",
            "id": 12345,
            "price": {},
            "metascore": "",
            "platforms": {},
        },
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"total": 0, "items": []}


def test_steam_parse_basic():
    p = SteamProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Portal 2"
    assert r.url == "https://store.steampowered.com/app/620/"
    assert "Price: 9.99 USD" in r.snippet
    assert "Metascore: 95" in r.snippet
    assert "Platforms: Windows, Linux" in r.snippet
    assert "Controller: full" in r.snippet
    assert r.source == "store.steampowered.com"
    assert r.provider == "steam"
    assert r.rank == 1
    assert r.extra["app_id"] == 620
    assert r.extra["type"] == "app"
    assert r.extra["metascore"] == "95"
    assert r.extra["platforms"] == ["Windows", "Linux"]
    assert r.extra["controller_support"] == "full"
    assert r.extra["thumbnail_url"] == "https://cdn.example.com/apps/620/capsule.jpg"


def test_steam_parse_free_item_has_no_price_snippet():
    p = SteamProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    r = result.results[1]
    assert r.title == "Free Game"
    assert "Price:" not in r.snippet
    assert r.extra["price"] == ""
    assert r.extra["platforms"] == ["Windows", "macOS", "Linux"]


def test_steam_parse_skips_item_without_name():
    p = SteamProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    assert len(result.results) == 2
    assert all(r.title for r in result.results)


def test_steam_parse_empty():
    p = SteamProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_steam_parse_non_dict():
    p = SteamProvider()
    result = p._parse([{"name": "x"}])
    assert result.results == []


def test_steam_parse_respects_limit():
    p = SteamProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    result.results = result.results[:1]
    assert len(result.results) == 1
    assert result.results[0].rank == 1


def test_steam_format_price():
    price = SteamProvider._format_price({"final": 5999, "currency": "USD"})
    assert price == "59.99 USD"
    assert SteamProvider._format_price({"final": 0, "currency": "USD"}) == ""
    assert SteamProvider._format_price({"final": None, "currency": "USD"}) == ""
    assert SteamProvider._format_price({}) == ""
    assert SteamProvider._format_price(None) == ""


def test_steam_is_available():
    """Keyless provider is always available."""
    assert SteamProvider().is_available() is True


@pytest.mark.asyncio
async def test_steam_search_hits_api_and_parses(respx_mock):
    """The search method hits the store search endpoint and parses the response."""
    import respx

    respx_mock.get("https://store.steampowered.com/api/storesearch").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = SteamProvider()
    result = await p.search("portal", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "steam"
    assert result.results[0].title == "Portal 2"


@pytest.mark.asyncio
async def test_steam_search_truncates_to_limit(respx_mock):
    """The search method truncates results to the requested limit."""
    import respx

    respx_mock.get("https://store.steampowered.com/api/storesearch").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = SteamProvider()
    result = await p.search("portal", SearchParams(num_results=1))

    assert len(result.results) == 1
    assert result.results[0].title == "Portal 2"


@pytest.mark.asyncio
async def test_steam_search_passes_query_param(respx_mock):
    """The search method forwards the query as the term parameter."""
    import respx

    route = respx_mock.get("https://store.steampowered.com/api/storesearch").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = SteamProvider()
    await p.search("portal 2", SearchParams(num_results=3))

    request = route.calls.last.request
    assert request.url.params["term"] == "portal 2"
