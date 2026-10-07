"""Unit tests for the MyAnimeList (Jikan API) anime provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.jikan import JikanProvider

_ENDPOINT = "https://api.jikan.moe/v4/anime"

_PAYLOAD = {
    "pagination": {
        "last_visible_page": 2,
        "has_next_page": True,
        "current_page": 1,
        "items": {"count": 2, "total": 42, "per_page": 25},
    },
    "data": [
        {
            "mal_id": 20,
            "url": "https://myanimelist.net/anime/20/Naruto",
            "images": {
                "jpg": {
                    "image_url": "https://cdn.myanimelist.net/images/anime/x.jpg",
                    "small_image_url": "https://cdn.myanimelist.net/images/anime/xt.jpg",
                    "large_image_url": "https://cdn.myanimelist.net/images/anime/xl.jpg",
                },
            },
            "title": "Naruto",
            "title_english": "Naruto",
            "title_japanese": "ナルト",
            "title_synonyms": ["NARUTO"],
            "type": "TV",
            "source": "Manga",
            "episodes": 220,
            "status": "Finished Airing",
            "airing": False,
            "aired": {
                "from": "2002-10-03T00:00:00+00:00",
                "to": "2007-02-08T00:00:00+00:00",
                "string": "Oct 3, 2002 to Feb 8, 2007",
            },
            "duration": "23 min per ep",
            "rating": "PG-13 - Teens 13 or older",
            "score": 7.99,
            "scored_by": 2500000,
            "rank": 1000,
            "popularity": 30,
            "members": 2900000,
            "favorites": 90000,
            "synopsis": "Naruto Uzumaki, a hyperactive ninja, seeks recognition.",
            "season": "fall",
            "year": 2002,
            "studios": [{"mal_id": 1, "name": "Studio Pierrot"}],
            "producers": [{"mal_id": 17, "name": "TV Tokyo"}],
            "licensors": [{"mal_id": 4, "name": "Viz Media"}],
            "genres": [
                {"mal_id": 1, "name": "Action"},
                {"mal_id": 2, "name": "Adventure"},
            ],
            "explicit_genres": [],
            "themes": [{"mal_id": 8, "name": "Martial Arts"}],
            "demographics": [{"mal_id": 27, "name": "Shounen"}],
        },
        {
            "mal_id": 999,
            "url": "",
            "title": "",
            "titles": [{"type": "Default", "title": "Fallback Title"}],
        },
        {"mal_id": None, "title": "No url and id"},
        "not-a-mapping",
    ],
}


def _mock(respx_mock, payload: object = _PAYLOAD):
    """Mock the Jikan anime search endpoint with *payload*."""
    return respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=payload),
    )


def _provider() -> JikanProvider:
    """Return a fresh provider instance for each test."""
    return JikanProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "jikan"
    assert p.tags == ["anime", "media"]
    assert "No API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "jikan" in registry
    assert registry["jikan"].tags == ["anime", "media"]


@pytest.mark.asyncio
async def test_search_builds_structured_result(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("naruto", SearchParams(num_results=10))
    anime = result.results[0]

    assert anime.title == "Naruto"
    assert anime.url == "https://myanimelist.net/anime/20/Naruto"
    assert anime.source == "myanimelist.net"
    assert anime.provider == "jikan"
    assert anime.rank == 1
    assert anime.published_date == "2002-10-03"
    assert anime.snippet == (
        "TV | Finished Airing | Fall 2002 | 220 episodes | score 7.99/10 | "
        "rank #1000 | 2,900,000 members | Action, Adventure | by Studio Pierrot"
    )
    assert anime.extra == {
        "mal_id": 20,
        "title_english": "Naruto",
        "title_japanese": "ナルト",
        "title_synonyms": ["NARUTO"],
        "type": "TV",
        "source": "Manga",
        "episodes": 220,
        "status": "Finished Airing",
        "airing": False,
        "aired": "Oct 3, 2002 to Feb 8, 2007",
        "duration": "23 min per ep",
        "rating": "PG-13 - Teens 13 or older",
        "score": 7.99,
        "scored_by": 2500000,
        "rank": 1000,
        "popularity": 30,
        "members": 2900000,
        "favourites": 90000,
        "season": "fall",
        "year": 2002,
        "studios": ["Studio Pierrot"],
        "producers": ["TV Tokyo"],
        "licensors": ["Viz Media"],
        "genres": ["Action", "Adventure"],
        "themes": ["Martial Arts"],
        "demographics": ["Shounen"],
        "synopsis": "Naruto Uzumaki, a hyperactive ninja, seeks recognition.",
        "image_url": "https://cdn.myanimelist.net/images/anime/xl.jpg",
        "total_results": 42,
    }


@pytest.mark.asyncio
async def test_search_falls_back_to_page_url_and_titles(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("naruto", SearchParams(num_results=10))
    fallback = result.results[1]

    assert fallback.title == "Fallback Title"
    assert fallback.url == "https://myanimelist.net/anime/999"
    assert fallback.rank == 2
    assert fallback.snippet == ""
    assert fallback.published_date is None
    assert fallback.extra["mal_id"] == 999
    assert fallback.extra["type"] is None
    assert fallback.extra["episodes"] is None
    assert fallback.extra["score"] is None
    assert fallback.extra["members"] is None
    assert fallback.extra["genres"] == []
    assert fallback.extra["image_url"] is None


@pytest.mark.asyncio
async def test_search_skips_incomplete_and_malformed_entries(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("naruto", SearchParams(num_results=10))

    assert [r.title for r in result.results] == ["Naruto", "Fallback Title"]
    assert [r.rank for r in result.results] == [1, 2]


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("naruto", SearchParams(num_results=1))

    assert [r.title for r in result.results] == ["Naruto"]


@pytest.mark.asyncio
async def test_search_sends_query_params_with_sfw(respx_mock) -> None:
    route = _mock(respx_mock)

    await _provider().search("fullmetal alchemist", SearchParams(num_results=5))

    params = route.calls.last.request.url.params
    assert params["q"] == "fullmetal alchemist"
    assert params["limit"] == "5"
    assert params["sfw"] == "true"


@pytest.mark.asyncio
async def test_search_omits_sfw_when_safe_search_disabled(respx_mock) -> None:
    route = _mock(respx_mock)

    await _provider().search(
        "naruto",
        SearchParams(num_results=5, safe_search=False),
    )

    params = route.calls.last.request.url.params
    assert "sfw" not in params


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    route = _mock(respx_mock)

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_handles_unexpected_payload_shapes(respx_mock) -> None:
    for payload in (
        ["not", "a", "mapping"],
        {},
        {"data": None},
        {"data": "nope"},
        {"pagination": "bad", "data": []},
    ):
        respx_mock.get(_ENDPOINT).mock(
            return_value=respx.MockResponse(200, json=payload),
        )
        result = await _provider().search("naruto", SearchParams(num_results=5))
        assert result.results == []


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("naruto", SearchParams(num_results=5))
