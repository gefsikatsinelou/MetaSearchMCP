"""Unit tests for the PokéAPI (Pokémon) search provider."""

from __future__ import annotations

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.pokeapi import PokeapiProvider

_API_BASE = "https://pokeapi.co/api/v2"


def _index(*entries: tuple[str, int]) -> dict:
    """A PokéAPI name-index response for the given ``(name, dex_id)`` pairs."""
    results = [
        {"name": name, "url": f"{_API_BASE}/pokemon/{dex_id}/"}
        for name, dex_id in entries
    ]
    return {"count": len(results), "next": None, "previous": None, "results": results}


def _detail(
    name: str,
    dex_id: int,
    *,
    types: list[str] | None = None,
    abilities: list[str] | None = None,
    height: int = 4,
    weight: int = 60,
    base_experience: int = 112,
    sprite: str | None = None,
) -> dict:
    """A PokéAPI Pokémon detail record with sensible defaults."""
    return {
        "id": dex_id,
        "name": name,
        "height": height,
        "weight": weight,
        "base_experience": base_experience,
        "types": [
            {"slot": i, "type": {"name": t}}
            for i, t in enumerate(types or ["electric"], 1)
        ],
        "abilities": [
            {"ability": {"name": a}, "is_hidden": False, "slot": i}
            for i, a in enumerate(abilities or ["static"], 1)
        ],
        "sprites": {
            "front_default": sprite
            or f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{dex_id}.png"
        },
    }


def _provider() -> PokeapiProvider:
    """Return a fresh provider instance for each test."""
    return PokeapiProvider()


def _mock_index(respx_mock, body: dict, status: int = 200):
    """Mock the name-index endpoint."""
    return respx_mock.get(f"{_API_BASE}/pokemon").mock(
        return_value=respx.MockResponse(status, json=body),
    )


def _mock_detail(respx_mock, name: str, body: dict, status: int = 200):
    """Mock one Pokémon detail endpoint."""
    return respx_mock.get(f"{_API_BASE}/pokemon/{name}").mock(
        return_value=respx.MockResponse(status, json=body),
    )


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "pokeapi"
    assert p.tags == ["media", "games", "fiction", "reference"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "pokeapi" in registry
    assert registry["pokeapi"].tags == ["media", "games", "fiction", "reference"]


def test_entries_ignores_malformed_payloads() -> None:
    p = _provider()
    assert p._entries(_index(("pikachu", 25))) == [
        {"name": "pikachu", "url": f"{_API_BASE}/pokemon/25/"}
    ]
    assert p._entries({}) == []
    assert p._entries({"results": "nonsense"}) == []
    assert p._entries({"results": [{"name": "x"}, None, "y"]}) == [{"name": "x"}]
    assert p._entries([]) == []
    assert p._entries(None) == []


def test_matches_ranks_exact_prefix_then_substring() -> None:
    entries = PokeapiProvider._entries(_index(("baa", 3), ("aab", 2), ("aa", 1)))

    matched = PokeapiProvider._matches(entries, "aa")

    assert matched == [(1, "aa"), (2, "aab"), (3, "baa")]


def test_matches_is_case_sensitive_against_lowered_names() -> None:
    entries = PokeapiProvider._entries(_index(("pikachu", 25)))
    assert PokeapiProvider._matches(entries, "PIKA") == []


def test_matches_skips_blank_names() -> None:
    entries = [
        {"name": "", "url": f"{_API_BASE}/pokemon/1/"},
        {"name": "ab", "url": ""},
    ]
    assert PokeapiProvider._matches(entries, "ab") == [(None, "ab")]


def test_build_result_uses_detail_fields() -> None:
    built = PokeapiProvider._build_result(
        _detail(
            "pikachu", 25, types=["electric"], abilities=["static", "lightning-rod"]
        ),
        25,
        "pikachu",
        1,
    )

    assert built.title == "Pikachu"
    assert built.url == f"{_API_BASE}/pokemon/25"
    assert built.source == "pokeapi.co"
    assert built.provider == "pokeapi"
    assert built.rank == 1
    assert (
        built.snippet == "#25 | type: electric | abilities: static, lightning-rod | "
        "0.4 m | 6 kg | base exp. 112"
    )
    assert built.extra["dex_id"] == 25
    assert built.extra["types"] == ["electric"]
    assert built.extra["abilities"] == ["static", "lightning-rod"]
    assert built.extra["sprite"].endswith("/25.png")


def test_build_result_prefers_detail_id_over_index_id() -> None:
    built = PokeapiProvider._build_result(_detail("pikachu", 25), None, "pikachu", 1)
    assert built.extra["dex_id"] == 25
    assert built.url == f"{_API_BASE}/pokemon/25"


def test_build_result_tolerates_missing_fields() -> None:
    built = PokeapiProvider._build_result(
        {"id": 1, "name": "missingno"},
        1,
        "missingno",
        2,
    )

    assert built is not None
    assert built.snippet == "#1"
    assert built.extra["dex_id"] == 1
    assert built.extra["types"] == []


def test_fallback_result_builds_minimal_hit() -> None:
    built = PokeapiProvider._fallback_result(25, "pikachu", 1)

    assert built.title == "Pikachu"
    assert built.url == f"{_API_BASE}/pokemon/25"
    assert built.snippet == "#25"
    assert built.extra == {
        "dex_id": 25,
        "sprite": "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/25.png",
    }


@pytest.mark.asyncio
async def test_search_returns_ranked_hits(respx_mock) -> None:
    _mock_index(respx_mock, _index(("pikachu", 25), ("raichu", 26), ("pichu", 172)))
    _mock_detail(respx_mock, "pikachu", _detail("pikachu", 25))
    _mock_detail(respx_mock, "raichu", _detail("raichu", 26))
    _mock_detail(respx_mock, "pichu", _detail("pichu", 172))

    result = await _provider().search("chu", SearchParams(num_results=10))

    assert [r.title for r in result.results] == ["Pikachu", "Raichu", "Pichu"]
    assert [r.rank for r in result.results] == [1, 2, 3]
    assert all(r.provider == "pokeapi" for r in result.results)


@pytest.mark.asyncio
async def test_search_trims_and_lowercases_query(respx_mock) -> None:
    route = _mock_index(respx_mock, _index(("pikachu", 25)))
    _mock_detail(respx_mock, "pikachu", _detail("pikachu", 25))

    await _provider().search("  PIKA  ", SearchParams(num_results=5))

    params = route.calls.last.request.url.params
    assert params["limit"] == "100000"


@pytest.mark.asyncio
async def test_search_truncates_to_limit(respx_mock) -> None:
    _mock_index(respx_mock, _index(("pika", 999), ("pikachu", 25), ("pichu", 172)))
    for name, dex in (("pika", 999), ("pikachu", 25)):
        _mock_detail(respx_mock, name, _detail(name, dex))

    result = await _provider().search("pika", SearchParams(num_results=2))

    assert [r.rank for r in result.results] == [1, 2]
    assert [r.title for r in result.results] == ["Pika", "Pikachu"]


@pytest.mark.asyncio
async def test_search_blank_query_skips_requests(respx_mock) -> None:
    route = _mock_index(respx_mock, _index(("pikachu", 25)))

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_no_match_returns_empty(respx_mock) -> None:
    _mock_index(respx_mock, _index(("pikachu", 25)))

    result = await _provider().search("zzzz", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_search_falls_back_when_detail_fails(respx_mock) -> None:
    _mock_index(respx_mock, _index(("pikachu", 25)))
    _mock_detail(respx_mock, "pikachu", {}, status=500)

    result = await _provider().search("pikachu", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].snippet == "#25"


@pytest.mark.asyncio
async def test_search_falls_back_when_detail_missing(respx_mock) -> None:
    _mock_index(respx_mock, _index(("pikachu", 25)))
    _mock_detail(respx_mock, "pikachu", {}, status=404)

    result = await _provider().search("pikachu", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].title == "Pikachu"


@pytest.mark.asyncio
async def test_search_raises_when_index_fails(respx_mock) -> None:
    _mock_index(respx_mock, {}, status=500)

    with pytest.raises(httpx.HTTPStatusError):
        await _provider().search("pikachu", SearchParams(num_results=5))
