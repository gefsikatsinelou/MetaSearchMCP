"""Unit tests for the Lemmy federated link aggregator provider."""

from __future__ import annotations

import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.lemmy import LemmyProvider

_SEARCH_PATH = "https://lemmy.world/api/v3/search"

_SAMPLE_RESPONSE: dict[str, object] = {
    "posts": [
        {
            "post": {
                "name": "Rust is eating the world",
                "url": "https://example.com/rust-article",
                "ap_id": "https://lemmy.world/post/123",
                "body": "A discussion about systems programming.",
                "published": "2025-07-01T10:00:00Z",
                "nsfw": False,
            },
            "creator": {"name": "devuser"},
            "community": {"name": "programming"},
            "counts": {"score": 128, "comments": 42},
        },
        {
            "post": {
                "name": "Link post without body",
                "url": None,
                "ap_id": "https://lemmy.ml/post/456",
                "body": None,
                "published": None,
                "nsfw": True,
            },
            "creator": {"name": "another"},
            "community": {"name": "memes"},
            "counts": {"score": 5, "comments": 0},
        },
    ]
}


def test_lemmy_name_and_tags():
    p = LemmyProvider()
    assert p.name == "lemmy"
    assert p.tags == ["social", "web", "news"]


def test_lemmy_parse_basic():
    p = LemmyProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Rust is eating the world"
    assert r.url == "https://example.com/rust-article"
    assert "systems programming" in r.snippet
    assert "Score: 128" in r.snippet
    assert "Comments: 42" in r.snippet
    assert r.provider == "lemmy"
    assert r.rank == 1
    assert r.source == "programming"
    assert r.published_date == "2025-07-01"
    assert r.extra["community"] == "programming"
    assert r.extra["username"] == "devuser"
    assert r.extra["score"] == 128
    assert r.extra["comments"] == 42


def test_lemmy_parse_link_post_without_body():
    p = LemmyProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    r = result.results[1]
    assert r.url == "https://lemmy.ml/post/456"
    assert "[link post from memes]" in r.snippet
    assert r.published_date is None
    assert r.extra["nsfw"] is True


def test_lemmy_parse_empty():
    p = LemmyProvider()
    result = p._parse({"posts": []})
    assert result.results == []


def test_lemmy_parse_missing_keys():
    p = LemmyProvider()
    result = p._parse({})
    assert result.results == []


@pytest.mark.asyncio
async def test_lemmy_search_hits_api_and_parses():
    async with respx.mock:
        respx.get(_SEARCH_PATH).mock(
            return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
        )
        p = LemmyProvider()
        result = await p.search("rust", SearchParams(num_results=5))

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Rust is eating the world"
    assert r.provider == "lemmy"


@pytest.mark.asyncio
async def test_lemmy_search_forwards_params():
    async with respx.mock:
        route = respx.get(_SEARCH_PATH).mock(
            return_value=respx.MockResponse(200, json={"posts": []}),
        )
        p = LemmyProvider()
        await p.search("hello world", SearchParams(num_results=3))

    request = route.calls.last.request
    assert request.url.params["q"] == "hello world"
    assert request.url.params["type_"] == "Posts"
    assert request.url.params["limit"] == "3"
    assert request.url.params["sort"] == "TopAll"
