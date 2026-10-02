"""Unit tests for the Yu-Gi-Oh! (YGOPRODeck) card search provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.yugioh import YuGiOhProvider

_API_URL = "https://db.ygoprodeck.com/api/v7/cardinfo.php"

_PAYLOAD = {
    "data": [
        {
            "id": 46986414,
            "name": "Dark Magician",
            "type": "Normal Monster",
            "humanReadableCardType": "Normal Monster",
            "frameType": "normal",
            "desc": "The ultimate wizard in terms of attack and defense.",
            "race": "Spellcaster",
            "attribute": "DARK",
            "archetype": "Dark Magician",
            "atk": 2500,
            "def": 2100,
            "level": 7,
            "ygoprodeck_url": "https://ygoprodeck.com/card/dark-magician-4003",
            "banlist_info": {"ban_tcg": "Limited", "ban_ocg": "Semi-Limited"},
            "card_sets": [
                {
                    "set_name": "Legend of Blue Eyes White Dragon",
                    "set_code": "LOB-005",
                },
            ],
            "card_prices": [{"tcgplayer_price": "0.36", "cardmarket_price": "0.02"}],
        },
        {
            "id": 34959756,
            "name": "Decode Talker",
            "type": "Link Monster",
            "humanReadableCardType": "Link Monster",
            "desc": "2+ Effect Monsters",
            "race": "Cyberse",
            "attribute": "DARK",
            "atk": 2300,
            "def": None,
            "level": 0,
            "linkval": 3,
            "card_sets": [],
            "card_prices": [],
        },
        {"id": 1},  # missing name -> skipped
        "not a dict",  # unexpected element -> skipped
    ],
    "meta": {"current_rows": 2},
}


def _provider() -> YuGiOhProvider:
    """Return a fresh provider instance for each test."""
    return YuGiOhProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "yugioh"
    assert p.tags == ["web", "media", "games", "cards"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "yugioh" in registry
    assert registry["yugioh"].tags == ["web", "media", "games", "cards"]


@pytest.mark.asyncio
async def test_search_builds_structured_results(respx_mock) -> None:
    route = respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_PAYLOAD),
    )

    result = await _provider().search("dark magic", SearchParams(num_results=10))

    assert route.called
    request = route.calls.last.request
    assert request.url.params["fname"] == "dark magic"
    assert request.url.params["num"] == "10"
    assert request.url.params["offset"] == "0"

    assert [r.title for r in result.results] == ["Dark Magician", "Decode Talker"]

    first = result.results[0]
    assert first.url == "https://ygoprodeck.com/card/dark-magician-4003"
    assert first.source == "db.ygoprodeck.com"
    assert first.provider == "yugioh"
    assert first.rank == 1
    assert first.snippet == (
        "Normal Monster | DARK/Spellcaster | Level 7 | ATK 2500 | DEF 2100 | "
        "Archetype: Dark Magician | The ultimate wizard in terms of attack "
        "and defense."
    )
    assert first.extra == {
        "id": 46986414,
        "type": "Normal Monster",
        "race": "Spellcaster",
        "attribute": "DARK",
        "archetype": "Dark Magician",
        "level": 7,
        "link_rating": None,
        "atk": 2500,
        "def": 2100,
        "banlist": "TCG Limited; OCG Semi-Limited",
        "first_set": "Legend of Blue Eyes White Dragon",
        "set_code": "LOB-005",
        "tcgplayer_price": "0.36",
    }

    link = result.results[1]
    assert link.rank == 2
    assert link.snippet == (
        "Link Monster | DARK/Cyberse | Link-3 | ATK 2300 | 2+ Effect Monsters"
    )
    assert link.extra["level"] == 0
    assert link.extra["link_rating"] == 3
    assert link.extra["def"] is None
    assert link.extra["banlist"] is None
    assert link.extra["first_set"] is None
    assert link.extra["tcgplayer_price"] is None


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    respx_mock.get(_API_URL).mock(return_value=respx.MockResponse(200, json=_PAYLOAD))

    result = await _provider().search("dark", SearchParams(num_results=1))

    assert len(result.results) == 1
    assert result.results[0].rank == 1


@pytest.mark.asyncio
async def test_search_unmatched_query_is_not_an_error(respx_mock) -> None:
    route = respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(
            400,
            json={"error": "No card matching your query was found in the database."},
        ),
    )

    result = await _provider().search("zzzznotacard", SearchParams(num_results=5))

    assert route.called
    assert result.results == []


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_API_URL).mock(return_value=respx.MockResponse(200))

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        "not a dict",
        ["a", "list"],
        {"data": "not a list"},
        {"data": [None, "x", 3, {}]},
        {},
    ],
)
async def test_search_handles_unexpected_payload_shapes(respx_mock, payload) -> None:
    respx_mock.get(_API_URL).mock(return_value=respx.MockResponse(200, json=payload))

    result = await _provider().search("dark", SearchParams(num_results=5))

    assert result.results == []


def test_build_result_returns_none_without_name() -> None:
    p = _provider()
    assert p._build_result({}, 1) is None
    assert p._build_result({"name": ""}, 1) is None
    assert p._build_result({"name": 123}, 1) is None


def test_build_result_falls_back_to_canonical_url() -> None:
    built = _provider()._build_result({"name": "Mystical Elf"}, 1)
    assert built is not None
    assert built.url == "https://ygoprodeck.com/card/?search=Mystical%20Elf"
    assert built.snippet == ""
    assert built.extra["atk"] is None
    assert built.extra["level"] is None


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_API_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("dark", SearchParams(num_results=5))
