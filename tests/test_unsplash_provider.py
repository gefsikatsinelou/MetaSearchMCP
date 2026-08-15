"""Unit tests for the Unsplash photo search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.unsplash import UnsplashProvider

_SAMPLE_RESPONSE = {
    "total": 2,
    "total_pages": 1,
    "results": [
        {
            "id": "photo-123",
            "created_at": "2026-08-01T09:30:00Z",
            "width": 4000,
            "height": 3000,
            "color": "#262626",
            "description": "A misty mountain lake at sunrise",
            "alt_description": "person standing on mountain",
            "urls": {
                "raw": "https://images.unsplash.com/photo-123?raw",
                "regular": "https://images.unsplash.com/photo-123?w=1080",
                "thumb": "https://images.unsplash.com/photo-123?w=200",
            },
            "links": {
                "html": "https://unsplash.com/photos/photo-123",
            },
            "user": {"name": "Alex Photographer", "username": "alexphoto"},
            "tags": [{"title": "mountain"}, {"title": "lake"}],
        },
        {
            "id": "photo-456",
            "created_at": "",
            "width": None,
            "height": None,
            "color": "",
            "description": "",
            "alt_description": "",
            "urls": {},
            "links": {"html": ""},
            "user": {"name": ""},
            "tags": [],
        },
    ],
}

_EMPTY_RESPONSE = {"total": 0, "total_pages": 0, "results": []}


def test_unsplash_parse_basic():
    p = UnsplashProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "person standing on mountain"
    assert r.url == "https://unsplash.com/photos/photo-123"
    assert "A misty mountain lake" in r.snippet
    assert "Photographer: Alex Photographer" in r.snippet
    assert "4000x3000" in r.snippet
    assert r.source == "unsplash.com"
    assert r.provider == "unsplash"
    assert r.rank == 1
    assert r.published_date == "2026-08-01"
    assert r.extra["thumbnail_url"] == "https://images.unsplash.com/photo-123?w=200"
    assert r.extra["image_url"] == "https://images.unsplash.com/photo-123?w=1080"
    assert r.extra["author"] == "Alex Photographer"
    assert r.extra["width"] == 4000
    assert r.extra["color"] == "#262626"
    assert r.extra["tags"] == ["mountain", "lake"]


def test_unsplash_parse_skips_item_without_link():
    p = UnsplashProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    assert len(result.results) == 1
    assert all(r.url for r in result.results)


def test_unsplash_parse_empty():
    p = UnsplashProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_unsplash_parse_respects_limit():
    p = UnsplashProvider()
    two_results = {
        "results": [
            {
                "id": f"p{i}",
                "links": {"html": f"https://unsplash.com/photos/p{i}"},
                "urls": {},
                "user": {},
                "tags": [],
            }
            for i in range(1, 3)
        ],
    }
    result = p._parse(two_results, limit=1)
    assert len(result.results) == 1
    assert result.results[0].rank == 1


def test_unsplash_clean():
    assert UnsplashProvider._clean("  hello   world  ") == "hello world"
    assert UnsplashProvider._clean("") == ""
    assert UnsplashProvider._clean(None) == ""


def test_unsplash_availability_requires_api_key(monkeypatch):
    from metasearchmcp.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "")
    assert UnsplashProvider().is_available() is False

    get_settings.cache_clear()
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "test-key")
    assert UnsplashProvider().is_available() is True
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_unsplash_search_hits_api_and_parses(respx_mock):
    """The search method hits the /search/photos endpoint and parses it."""
    import respx

    respx_mock.get("https://api.unsplash.com/search/photos").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = UnsplashProvider()
    result = await p.search("mountain", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "unsplash"
    assert result.results[0].title == "person standing on mountain"
