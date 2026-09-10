"""Unit tests for the Scryfall Magic: The Gathering card search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.scryfall import ScryfallProvider

_SAMPLE_RESPONSE: dict[str, object] = {
    "object": "list",
    "total_cards": 5,
    "has_more": False,
    "data": [
        {
            "object": "card",
            "name": "Grizzly Bears",
            "mana_cost": "{1}{G}",
            "type_line": "Creature — Bear",
            "oracle_text": "",
            "set": "10e",
            "set_name": "Tenth Edition",
            "collector_number": "268",
            "rarity": "common",
            "released_at": "2007-07-13",
            "scryfall_uri": (
                "https://scryfall.com/card/10e/268/grizzly-bears?utm_source=api"
            ),
            "artist": "D. J. Cleland-Hura",
            "cmc": 2.0,
            "colors": ["G"],
            "prices": {
                "usd": "0.23",
                "usd_foil": "3.29",
                "eur": "0.18",
                "tix": "0.03",
            },
            "image_uris": {"normal": "https://cards.scryfall.io/normal/front/409.jpg"},
        },
        {
            # Double-faced card: no top-level oracle_text or mana_cost.
            "object": "card",
            "name": "Emeritus of Conflict // Lightning Bolt",
            "type_line": "Creature — Human Wizard // Instant",
            "set": "sos",
            "set_name": "Secrets of Strixhaven",
            "collector_number": "113",
            "rarity": "mythic",
            "released_at": "2026-04-24",
            "card_faces": [
                {"oracle_text": "First strike", "mana_cost": "{1}{R}"},
                {"oracle_text": "Lightning Bolt deals 3 damage to any target."},
            ],
            "prices": {"usd": None, "eur": None, "tix": "1.20"},
        },
        {
            # No released_at and no scryfall_uri -> date None, URL from set/number.
            "name": "Sol Ring",
            "type_line": "Artifact",
            "oracle_text": "{T}: Add {C}{C}.",
            "set": "ltc",
            "set_name": "Tales of Middle-earth Commander",
            "collector_number": "280",
            "rarity": "uncommon",
            "prices": {"usd": "1.50"},
        },
        {
            # Missing name -> skipped.
            "type_line": "Sorcery",
        },
        "junk",
        None,
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {
    "object": "list",
    "total_cards": 0,
    "has_more": False,
    "data": [],
}


def _provider() -> ScryfallProvider:
    return ScryfallProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "scryfall"
    assert p.tags == ["web", "media", "games", "cards"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 3
    r = result.results[0]
    assert r.title == "Grizzly Bears"
    # Tracking query string is stripped from the returned link.
    assert r.url == "https://scryfall.com/card/10e/268/grizzly-bears"
    assert "Creature — Bear" in r.snippet
    assert "Common" in r.snippet
    assert "Tenth Edition (10E)" in r.snippet
    assert "$0.23 / €0.18" in r.snippet
    assert r.source == "scryfall.com"
    assert r.provider == "scryfall"
    assert r.rank == 1
    assert r.published_date == "2007-07-13"
    assert r.extra["mana_cost"] == "{1}{G}"
    assert r.extra["rarity"] == "common"
    assert r.extra["set"] == "10E"
    assert r.extra["set_name"] == "Tenth Edition"
    assert r.extra["artist"] == "D. J. Cleland-Hura"
    assert r.extra["cmc"] == 2.0
    assert r.extra["colors"] == ["G"]
    assert r.extra["prices"]["usd"] == "0.23"
    assert r.extra["image_url"] == "https://cards.scryfall.io/normal/front/409.jpg"


def test_parse_multiface_joins_oracle_text_and_mana_cost() -> None:
    r = _provider()._parse(_SAMPLE_RESPONSE).results[1]
    assert "First strike // Lightning Bolt deals 3 damage" in r.snippet
    assert r.extra["oracle_text"] == (
        "First strike // Lightning Bolt deals 3 damage to any target."
    )
    # Mana cost falls back to the first face.
    assert r.extra["mana_cost"] == "{1}{R}"
    # No scryfall_uri -> derived from set + collector number.
    assert r.url == "https://scryfall.com/card/sos/113"
    # Only tix is priced -> no USD/EUR summary in the snippet.
    assert "$" not in r.snippet
    assert "Mythic" in r.snippet


def test_parse_missing_date_and_url_fallback() -> None:
    r = _provider()._parse(_SAMPLE_RESPONSE).results[2]
    assert r.published_date is None
    assert r.url == "https://scryfall.com/card/ltc/280"
    assert r.extra["image_url"] == ""
    assert "$1.50" in r.snippet


def test_parse_skips_nameless_and_non_dict_items() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert len(result.results) == 3
    assert all(r.title for r in result.results)


def test_parse_limit_and_empty() -> None:
    p = _provider()
    assert len(p._parse(_SAMPLE_RESPONSE, limit=1).results) == 1
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse("junk").results == []  # type: ignore[arg-type]
    assert p._parse(None).results == []  # type: ignore[arg-type]
    assert p._parse({}).results == []  # type: ignore[arg-type]


def test_parse_accepts_top_level_list() -> None:
    p = _provider()
    result = p._parse(_SAMPLE_RESPONSE["data"])  # type: ignore[arg-type]
    assert len(result.results) == 3


def test_parse_snippet_capped_at_shared_limit() -> None:
    from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH

    long_text = "x" * (MAX_SNIPPET_LENGTH + 200)
    result = _provider()._parse(
        {
            "data": [
                {
                    "name": "Long",
                    "type_line": "Instant",
                    "oracle_text": long_text,
                    "set": "tst",
                    "set_name": "Test",
                    "rarity": "rare",
                }
            ]
        }
    )
    assert len(result.results[0].snippet) == MAX_SNIPPET_LENGTH


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_query(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.scryfall.com/cards/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("lightning bolt", SearchParams(num_results=5))

    assert len(result.results) == 3
    request = respx_mock.calls.last.request
    assert request.url.params["q"] == "lightning bolt"
    assert request.url.params["order"] == "name"
    assert request.url.params["limit"] == "5"


@pytest.mark.asyncio
async def test_search_no_results_returns_empty(respx_mock) -> None:
    import respx

    # Scryfall signals "no matches" with HTTP 404.
    respx_mock.get("https://api.scryfall.com/cards/search").mock(
        return_value=respx.MockResponse(
            404,
            json={
                "object": "error",
                "code": "not_found",
                "status": 404,
                "details": "Your query didn't match any cards.",
            },
        ),
    )

    p = _provider()
    result = await p.search("zzzznotacard", SearchParams(num_results=5))
    assert result.results == []


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.scryfall.com/cards/search").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("no-such-card-xyz", SearchParams(num_results=5))
    assert result.results == []
