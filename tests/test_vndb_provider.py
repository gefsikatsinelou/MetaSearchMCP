"""Unit tests for the VNDB (Visual Novel Database) provider."""

from __future__ import annotations

import json

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.vndb import VNDBProvider

_API_URL = "https://api.vndb.org/kana/vn"

_PAYLOAD = {
    "more": False,
    "results": [
        {
            "id": "v31477",
            "title": "Café Milan",
            "alttitle": "カフェミラノ",
            "released": "2021-07-01",
            "rating": 68.2,
            "votecount": 42,
            "image": {"url": "https://t.vndb.org/cv/17/48417.jpg"},
            "description": "A postgrad student takes a job at a swanky café.",
            "developers": [{"id": "p12094", "name": "VOWtogether"}],
            "platforms": ["win", "mac"],
        },
        {
            "id": "v11",
            "title": "Fate/stay night",
            "alttitle": None,
            "released": "2004",
            "rating": None,
            "votecount": 0,
            "image": None,
            "description": None,
            "developers": [],
            "platforms": ["win"],
        },
    ],
}


def _provider() -> VNDBProvider:
    """Return a fresh provider instance for each test."""
    return VNDBProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "vndb"
    assert p.tags == ["web", "games", "media"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "vndb" in registry
    assert registry["vndb"].tags == ["web", "games", "media"]


@pytest.mark.asyncio
async def test_search_builds_structured_results(respx_mock) -> None:
    route = respx_mock.post(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_PAYLOAD),
    )

    result = await _provider().search("cafe", SearchParams(num_results=10))

    assert route.called
    assert [r.title for r in result.results] == ["Café Milan", "Fate/stay night"]

    first = result.results[0]
    assert first.url == "https://vndb.org/v31477"
    assert first.source == "vndb.org"
    assert first.provider == "vndb"
    assert first.rank == 1
    assert first.snippet == (
        "カフェミラノ | 2021-07-01 · rating 68.2 · 42 votes · VOWtogether | "
        "A postgrad student takes a job at a swanky café."
    )
    assert first.extra == {
        "id": "v31477",
        "alttitle": "カフェミラノ",
        "released": "2021-07-01",
        "rating": 68.2,
        "votecount": 42,
        "developers": ["VOWtogether"],
        "platforms": ["win", "mac"],
        "image_url": "https://t.vndb.org/cv/17/48417.jpg",
    }

    # Second entry has no alt title, rating, description or developers.
    second = result.results[1]
    assert second.rank == 2
    assert second.snippet == "2004"
    assert second.extra["rating"] is None
    assert second.extra["alttitle"] is None
    assert second.extra["image_url"] is None


@pytest.mark.asyncio
async def test_search_sends_search_filter_and_limit(respx_mock) -> None:
    route = respx_mock.post(_API_URL).mock(
        return_value=respx.MockResponse(200, json={"results": []}),
    )

    await _provider().search("fate", SearchParams(num_results=3))

    request = route.calls.last.request
    body = json.loads(request.content)
    assert body["filters"] == ["search", "=", "fate"]
    assert body["results"] == 3
    assert body["sort"] == "searchrank"


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    respx_mock.post(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_PAYLOAD),
    )

    result = await _provider().search("cafe", SearchParams(num_results=1))

    assert len(result.results) == 1
    assert result.results[0].rank == 1


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.post(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_PAYLOAD),
    )

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        "not a dict",
        ["a", "list"],
        {"results": "not a list"},
        {"results": [None, "x", 3, {}]},
        {},
    ],
)
async def test_search_handles_unexpected_payload_shapes(respx_mock, payload) -> None:
    respx_mock.post(_API_URL).mock(
        return_value=respx.MockResponse(200, json=payload),
    )

    result = await _provider().search("cafe", SearchParams(num_results=5))

    assert result.results == []


def test_description_strips_vndb_formatting() -> None:
    item = {
        "id": "v1",
        "title": "Test",
        "description": "See [url=/v2]the sequel[/url].[spoiler]Hidden[/spoiler]",
    }
    built = _provider()._build_result(item, 1)
    assert built is not None
    assert built.snippet == "See the sequel . Hidden"


def test_build_result_returns_none_without_id_or_title() -> None:
    p = _provider()
    assert p._build_result({"title": "No id"}, 1) is None
    assert p._build_result({"id": "v9"}, 1) is None


def test_build_result_falls_back_to_alttitle() -> None:
    built = _provider()._build_result(
        {"id": "v9", "title": None, "alttitle": "Romaji Title"},
        1,
    )
    assert built is not None
    assert built.title == "Romaji Title"


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.post(_API_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("cafe", SearchParams(num_results=5))
