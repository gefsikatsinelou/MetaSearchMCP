"""Unit tests for the Star Wars (SWAPI) search provider."""

from __future__ import annotations

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.swapi import _RESOURCES, SwapiProvider

_API_BASE = "https://swapi.dev/api"


def _person(**over) -> dict:
    """A SWAPI people record with sensible defaults."""
    item = {
        "name": "Luke Skywalker",
        "height": "172",
        "mass": "77",
        "gender": "male",
        "birth_year": "19BBY",
        "created": "2014-12-09T13:50:51.644000Z",
        "url": "https://swapi.dev/api/people/1/",
    }
    item.update(over)
    return item


def _film(**over) -> dict:
    """A SWAPI film record with sensible defaults."""
    item = {
        "title": "A New Hope",
        "episode_id": 4,
        "director": "George Lucas",
        "release_date": "1977-05-25",
        "created": "2014-12-10T14:23:31.880000Z",
        "url": "https://swapi.dev/api/films/1/",
    }
    item.update(over)
    return item


def _planet(**over) -> dict:
    """A SWAPI planet record with sensible defaults."""
    item = {
        "name": "Tatooine",
        "climate": "arid",
        "terrain": "desert",
        "gravity": "1 standard",
        "population": "200000",
        "created": "2014-12-09T13:50:49.641000Z",
        "url": "https://swapi.dev/api/planets/1/",
    }
    item.update(over)
    return item


def _page(*items: dict) -> dict:
    """A SWAPI paginated response body containing the given records."""
    return {
        "count": len(items),
        "next": None,
        "previous": None,
        "results": list(items),
    }


def _provider() -> SwapiProvider:
    """Return a fresh provider instance for each test."""
    return SwapiProvider()


def _mock_all(respx_mock, payloads: dict[str, dict] | None = None, status: int = 200):
    """Mock every SWAPI collection endpoint, defaulting to empty pages."""
    payloads = payloads or {}
    routes = {}
    for resource in _RESOURCES:
        body = payloads.get(resource, _page())
        routes[resource] = respx_mock.get(f"{_API_BASE}/{resource}/").mock(
            return_value=respx.MockResponse(status, json=body),
        )
    return routes


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "swapi"
    assert p.tags == ["media", "entertainment", "fiction", "reference"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "swapi" in registry
    assert registry["swapi"].tags == [
        "media",
        "entertainment",
        "fiction",
        "reference",
    ]


def test_items_ignores_malformed_payloads() -> None:
    p = _provider()
    assert p._items(_page(_person())) == [_person()]
    assert p._items({}) == []
    assert p._items({"results": "nonsense"}) == []
    assert p._items([]) == []
    assert p._items(None) == []
    assert p._items({"results": [_person(), None, "x"]}) == [_person()]


def test_build_result_person() -> None:
    built = SwapiProvider._build_result("people", _person(), 1)

    assert built is not None
    assert built.title == "Luke Skywalker"
    assert built.url == "https://swapi.dev/api/people/1/"
    assert built.source == "swapi.dev"
    assert built.provider == "swapi"
    assert built.rank == 1
    assert built.published_date == "2014-12-09"
    assert built.snippet == "male | 172 cm | 77 kg | born 19BBY"
    assert built.extra == {"resource": "people"}


def test_build_result_film_uses_title_and_release_date() -> None:
    built = SwapiProvider._build_result("films", _film(), 2)

    assert built is not None
    assert built.title == "A New Hope"
    assert built.published_date == "1977-05-25"
    assert built.snippet == "Episode 4 | dir. George Lucas | 1977-05-25"
    assert built.extra == {"resource": "films"}


def test_build_result_planet() -> None:
    built = SwapiProvider._build_result("planets", _planet(), 1)

    assert built is not None
    assert built.snippet == "arid | desert | 1 standard | pop. 200000"


def test_snippet_drops_unknown_placeholders() -> None:
    built = SwapiProvider._build_result("people", _person(mass="unknown"), 1)

    assert built is not None
    assert built.snippet == "male | 172 cm | born 19BBY"


def test_build_result_skips_missing_title_or_url() -> None:
    assert SwapiProvider._build_result("people", _person(name=""), 1) is None
    assert SwapiProvider._build_result("people", _person(url=""), 1) is None


def test_interleave_round_robins_collections() -> None:
    groups = [
        ("people", [_person(name="A"), _person(name="B")]),
        ("films", [_film()]),
    ]

    ordered = SwapiProvider._interleave(groups)

    assert [resource for resource, _ in ordered] == ["people", "films", "people"]
    assert ordered[0][1]["name"] == "A"
    assert ordered[1][1]["title"] == "A New Hope"
    assert ordered[2][1]["name"] == "B"


@pytest.mark.asyncio
async def test_search_interleaves_and_ranks(respx_mock) -> None:
    _mock_all(
        respx_mock,
        {
            "people": _page(_person(name="Luke"), _person(name="Leia")),
            "films": _page(_film(title="A New Hope")),
        },
    )

    result = await _provider().search("hope", SearchParams(num_results=10))

    assert [r.title for r in result.results] == ["Luke", "A New Hope", "Leia"]
    assert [r.rank for r in result.results] == [1, 2, 3]
    assert [r.extra["resource"] for r in result.results] == [
        "people",
        "films",
        "people",
    ]
    assert all(r.provider == "swapi" for r in result.results)


@pytest.mark.asyncio
async def test_search_sends_trimmed_query(respx_mock) -> None:
    routes = _mock_all(respx_mock, {"people": _page(_person())})

    await _provider().search("  luke  ", SearchParams(num_results=5))

    params = routes["people"].calls.last.request.url.params
    assert params["search"] == "luke"


@pytest.mark.asyncio
async def test_search_truncates_to_limit(respx_mock) -> None:
    _mock_all(
        respx_mock,
        {
            "people": _page(_person(name="A"), _person(name="B")),
            "films": _page(_film(title="C")),
        },
    )

    result = await _provider().search("x", SearchParams(num_results=2))

    assert [r.rank for r in result.results] == [1, 2]


@pytest.mark.asyncio
async def test_search_blank_query_skips_requests(respx_mock) -> None:
    routes = _mock_all(respx_mock)

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not any(route.called for route in routes.values())


@pytest.mark.asyncio
async def test_search_tolerates_partial_failure(respx_mock) -> None:
    routes = _mock_all(respx_mock, {"films": _page(_film(title="A New Hope"))})
    routes["people"].mock(return_value=respx.MockResponse(500, json={}))

    result = await _provider().search("hope", SearchParams(num_results=10))

    assert [r.title for r in result.results] == ["A New Hope"]


@pytest.mark.asyncio
async def test_search_raises_when_all_collections_fail(respx_mock) -> None:
    _mock_all(respx_mock, status=500)

    with pytest.raises(httpx.HTTPStatusError):
        await _provider().search("hope", SearchParams(num_results=5))
