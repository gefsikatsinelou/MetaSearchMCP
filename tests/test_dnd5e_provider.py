"""Unit tests for the D&D 5e reference search provider."""

from __future__ import annotations

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.dnd5e import (
    _API_BASE,
    _SITE_BASE,
    Dnd5eProvider,
)

_SPELLS_ROUTE = r"https://www\.dnd5eapi\.co/api/2014/spells.*"
_MONSTERS_ROUTE = r"https://www\.dnd5eapi\.co/api/2014/monsters.*"
_EQUIPMENT_ROUTE = r"https://www\.dnd5eapi\.co/api/2014/equipment.*"


def _entry(name: str, slug: str, collection: str, **extra) -> dict:
    """A 5e API list entry for *name* in *collection*."""
    item = {
        "index": slug,
        "name": name,
        "url": f"/api/2014/{collection}/{slug}",
    }
    item.update(extra)
    return item


def _payload(*entries: object) -> dict:
    """Wrap raw *entries* in the ``{count, results}`` envelope the API returns."""
    results = [entry for entry in entries if isinstance(entry, dict)]
    return {"count": len(results), "results": list(entries)}


def _provider() -> Dnd5eProvider:
    """Return a fresh provider instance for each test."""
    return Dnd5eProvider()


def _mock_collection(respx_mock, pattern, *, entries=None, status=200, exc=None):
    """Register a mock for one collection endpoint and return the route."""
    if exc is not None:
        return respx_mock.get(url__regex=pattern).mock(side_effect=exc)
    return respx_mock.get(url__regex=pattern).mock(
        return_value=respx.MockResponse(status, json=_payload(*(entries or []))),
    )


def _mock(
    respx_mock,
    *,
    spells: list[dict] | None = None,
    monsters: list[dict] | None = None,
    equipment: list[dict] | None = None,
):
    """Mock the three collection endpoints, defaulting each to an empty result."""
    return [
        _mock_collection(respx_mock, _SPELLS_ROUTE, entries=spells),
        _mock_collection(respx_mock, _MONSTERS_ROUTE, entries=monsters),
        _mock_collection(respx_mock, _EQUIPMENT_ROUTE, entries=equipment),
    ]


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "dnd5e"
    assert p.tags == ["games", "reference", "fiction", "web"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "dnd5e" in registry
    assert registry["dnd5e"].tags == ["games", "reference", "fiction", "web"]


def test_entries_ignores_malformed_payloads() -> None:
    p = _provider()
    fireball = _entry("Fireball", "fireball", "spells")
    assert p._entries(_payload(fireball)) == [fireball]
    assert p._entries({"count": 0, "results": []}) == []
    assert p._entries(None) == []
    assert p._entries("nonsense") == []
    assert p._entries({"results": "nope"}) == []
    assert p._entries(_payload(fireball, None, "x", 3)) == [fireball]


def test_build_result_formats_spell_with_level() -> None:
    built = Dnd5eProvider._build_result(
        _entry("Fireball", "fireball", "spells", level=3),
        "Spell",
        1,
    )

    assert built is not None
    assert built.title == "Fireball"
    assert built.url == f"{_SITE_BASE}/api/2014/spells/fireball"
    assert built.source == "dnd5eapi.co"
    assert built.provider == "dnd5e"
    assert built.rank == 1
    assert built.snippet == "Spell | level 3"
    assert built.extra == {"type": "spell", "index": "fireball", "level": 3}


def test_build_result_formats_monster_without_level() -> None:
    built = Dnd5eProvider._build_result(
        _entry("Adult Black Dragon", "adult-black-dragon", "monsters"),
        "Monster",
        2,
    )

    assert built is not None
    assert built.snippet == "Monster"
    assert built.extra == {"type": "monster", "index": "adult-black-dragon"}


def test_build_result_skips_missing_name() -> None:
    assert Dnd5eProvider._build_result({"index": "x"}, "Spell", 1) is None
    assert Dnd5eProvider._build_result({"name": "  "}, "Spell", 1) is None


def test_build_result_tolerates_missing_url() -> None:
    built = Dnd5eProvider._build_result({"name": "Mystery"}, "Equipment", 1)

    assert built is not None
    assert built.url == _API_BASE
    assert built.extra == {"type": "equipment"}


def test_tier_ranks_exact_prefix_then_substring() -> None:
    assert Dnd5eProvider._tier("Fireball", "fireball") == 0
    assert Dnd5eProvider._tier("Fire Bolt", "fire") == 1
    assert Dnd5eProvider._tier("Delayed Blast Fireball", "fire") == 2


@pytest.mark.asyncio
async def test_search_ranks_exact_before_prefix_before_substring(respx_mock) -> None:
    _mock(
        respx_mock,
        spells=[
            _entry("Delayed Blast Fireball", "dbf", "spells", level=7),
            _entry("Fire Bolt", "fire-bolt", "spells", level=0),
            _entry("Fireball", "fireball", "spells", level=3),
        ],
    )

    result = await _provider().search("fireball", SearchParams(num_results=10))

    assert [r.title for r in result.results] == [
        "Fireball",
        "Delayed Blast Fireball",
        "Fire Bolt",
    ]
    assert [r.rank for r in result.results] == [1, 2, 3]


@pytest.mark.asyncio
async def test_search_merges_collections(respx_mock) -> None:
    _mock(
        respx_mock,
        spells=[_entry("Fireball", "fireball", "spells", level=3)],
        monsters=[_entry("Fire Elemental", "fire-elemental", "monsters")],
        equipment=[_entry("Firearm", "firearm", "equipment")],
    )

    result = await _provider().search("fire", SearchParams(num_results=10))

    assert [r.title for r in result.results] == [
        "Fireball",
        "Fire Elemental",
        "Firearm",
    ]
    assert [r.extra["type"] for r in result.results] == [
        "spell",
        "monster",
        "equipment",
    ]


@pytest.mark.asyncio
async def test_search_sends_name_param(respx_mock) -> None:
    routes = _mock(respx_mock, spells=[_entry("Fireball", "fireball", "spells")])

    await _provider().search("  fireball  ", SearchParams(num_results=5))

    request = routes[0].calls.last.request
    assert request.url.params["name"] == "fireball"
    assert request.url.path == "/api/2014/spells"


@pytest.mark.asyncio
async def test_search_truncates_to_limit(respx_mock) -> None:
    _mock(
        respx_mock,
        spells=[
            _entry("A", "a", "spells"),
            _entry("B", "b", "spells"),
            _entry("C", "c", "spells"),
        ],
    )

    result = await _provider().search("x", SearchParams(num_results=1))

    assert [r.rank for r in result.results] == [1]


@pytest.mark.asyncio
async def test_search_blank_query_skips_requests(respx_mock) -> None:
    routes = _mock(respx_mock, spells=[_entry("Fireball", "fireball", "spells")])

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert all(not route.called for route in routes)


@pytest.mark.asyncio
async def test_search_no_matches_returns_empty(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("zzzznope", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_search_treats_404_as_empty(respx_mock) -> None:
    _mock_collection(respx_mock, _SPELLS_ROUTE, status=404)
    _mock_collection(
        respx_mock,
        _MONSTERS_ROUTE,
        entries=[_entry("Adult Black Dragon", "adult-black-dragon", "monsters")],
    )
    _mock_collection(respx_mock, _EQUIPMENT_ROUTE)

    result = await _provider().search("dragon", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["Adult Black Dragon"]


@pytest.mark.asyncio
async def test_search_skips_failing_collection(respx_mock) -> None:
    _mock_collection(respx_mock, _SPELLS_ROUTE, status=500)
    _mock_collection(respx_mock, _MONSTERS_ROUTE)
    _mock_collection(
        respx_mock,
        _EQUIPMENT_ROUTE,
        entries=[_entry("Longsword", "longsword", "equipment")],
    )

    result = await _provider().search("longsword", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["Longsword"]


@pytest.mark.asyncio
async def test_search_isolates_transport_error(respx_mock) -> None:
    _mock_collection(
        respx_mock,
        _SPELLS_ROUTE,
        exc=httpx.ConnectError("no network"),
    )
    _mock_collection(
        respx_mock,
        _MONSTERS_ROUTE,
        entries=[_entry("Adult Black Dragon", "adult-black-dragon", "monsters")],
    )
    _mock_collection(respx_mock, _EQUIPMENT_ROUTE)

    result = await _provider().search("black", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["Adult Black Dragon"]
