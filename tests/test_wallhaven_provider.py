"""Unit tests for the Wallhaven wallpaper provider."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.wallhaven import WallhavenProvider

_ENDPOINT = "https://wallhaven.cc/api/v1/search"
_WALLPAPER_ID = "48d6rj"

_WALLPAPER: dict[str, Any] = {
    "id": _WALLPAPER_ID,
    "url": f"https://wallhaven.cc/w/{_WALLPAPER_ID}",
    "short_url": f"https://whvn.cc/{_WALLPAPER_ID}",
    "views": 10116,
    "favorites": 28,
    "source": "https://example.com/original",
    "purity": "sfw",
    "category": "anime",
    "dimension_x": 1920,
    "dimension_y": 1080,
    "resolution": "1920x1080",
    "ratio": "1.78",
    "file_size": 292334,
    "file_type": "image/jpeg",
    "created_at": "2014-12-08 05:20:39",
    "colors": ["#000000", "#424153", "#999999", "#e7d8b1", "#663300"],
    "path": f"https://w.wallhaven.cc/full/48/wallhaven-{_WALLPAPER_ID}.jpg",
    "thumbs": {
        "large": f"https://th.wallhaven.cc/lg/48/{_WALLPAPER_ID}.jpg",
        "original": f"https://th.wallhaven.cc/orig/48/{_WALLPAPER_ID}.jpg",
        "small": f"https://th.wallhaven.cc/small/48/{_WALLPAPER_ID}.jpg",
    },
}

_NSFW: dict[str, Any] = {
    "id": "lyd9gp",
    "url": "https://wallhaven.cc/w/lyd9gp",
    "purity": "nsfw",
    "category": "people",
    "resolution": "3027x4096",
    "file_size": 2594101,
    "file_type": "image/png",
    "colors": [],
    "views": 0,
}

_SPARSE: dict[str, Any] = {"id": "sparse"}


def _envelope(records: list[Any], total: int | None = 42) -> dict[str, Any]:
    """Wrap *records* in a Wallhaven search response envelope."""
    return {
        "data": records,
        "meta": {
            "current_page": 1,
            "last_page": 205,
            "per_page": 24,
            "total": total,
            "query": "anime",
            "seed": None,
        },
    }


def test_wallhaven_name_tags_and_availability() -> None:
    p = WallhavenProvider()
    assert p.name == "wallhaven"
    assert p.tags == ["image", "media", "wallpaper"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_wallhaven_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "wallhaven" in registry
    assert registry["wallhaven"].tags == ["image", "media", "wallpaper"]


def test_wallhaven_parse_record() -> None:
    p = WallhavenProvider()
    result = p._parse(_envelope([_WALLPAPER]), limit=5)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "1920x1080 Anime wallpaper"
    assert r.url == f"https://wallhaven.cc/w/{_WALLPAPER_ID}"
    assert r.source == "wallhaven.cc"
    assert r.provider == "wallhaven"
    assert r.rank == 1
    assert r.published_date == "2014-12-08"
    assert r.snippet == (
        "1920x1080 | 285 KB | jpeg | Anime | "
        "#000000 #424153 #999999 #e7d8b1 #663300 | 10,116 views | 28 favorites"
    )
    assert r.extra["wallhaven_id"] == _WALLPAPER_ID
    assert r.extra["resolution"] == "1920x1080"
    assert r.extra["width"] == 1920
    assert r.extra["height"] == 1080
    assert r.extra["aspect_ratio"] == "1.78"
    assert r.extra["category"] == "anime"
    assert r.extra["purity"] == "sfw"
    assert r.extra["file_size"] == 292334
    assert r.extra["file_size_human"] == "285 KB"
    assert r.extra["file_type"] == "image/jpeg"
    assert r.extra["image_url"] == (
        f"https://w.wallhaven.cc/full/48/wallhaven-{_WALLPAPER_ID}.jpg"
    )
    assert r.extra["thumbnail_url"] == (
        f"https://th.wallhaven.cc/orig/48/{_WALLPAPER_ID}.jpg"
    )
    assert r.extra["short_url"] == f"https://whvn.cc/{_WALLPAPER_ID}"
    assert r.extra["colors"] == [
        "#000000",
        "#424153",
        "#999999",
        "#e7d8b1",
        "#663300",
    ]
    assert r.extra["views"] == 10116
    assert r.extra["favorites"] == 28
    assert r.extra["source_url"] == "https://example.com/original"
    assert r.extra["total_results"] == 42


def test_wallhaven_snippet_reveals_adult_purity() -> None:
    p = WallhavenProvider()
    r = p._parse(_envelope([_NSFW])).results[0]

    assert r.title == "3027x4096 People wallpaper"
    assert r.snippet == "3027x4096 | 2.5 MB | png | People | NSFW | 0 views"
    assert r.extra["thumbnail_url"] is None
    assert r.extra["image_url"] is None
    assert r.extra["colors"] == []
    assert r.extra["source_url"] is None


def test_wallhaven_sparse_record_falls_back_to_identifier() -> None:
    p = WallhavenProvider()
    r = p._parse(_envelope([_SPARSE], total=None)).results[0]

    assert r.title == "Wallhaven sparse"
    assert r.url == "https://wallhaven.cc/w/sparse"
    assert r.snippet == ""
    assert r.published_date is None
    assert r.extra["resolution"] is None
    assert r.extra["views"] is None
    assert r.extra["favorites"] is None
    assert r.extra["total_results"] is None


def test_wallhaven_thumbnail_falls_back_to_large() -> None:
    p = WallhavenProvider()
    item = dict(_WALLPAPER, thumbs={"large": "https://th.wallhaven.cc/lg/x.jpg"})
    r = p._parse(_envelope([item])).results[0]
    assert r.extra["thumbnail_url"] == "https://th.wallhaven.cc/lg/x.jpg"

    no_thumbs = dict(_WALLPAPER, thumbs="nope")
    assert p._parse(_envelope([no_thumbs])).results[0].extra["thumbnail_url"] is None


def test_wallhaven_parse_skips_records_without_id() -> None:
    p = WallhavenProvider()
    payload = _envelope([{}, {"id": ""}, "nope", _WALLPAPER])
    results = p._parse(payload).results
    assert [r.extra["wallhaven_id"] for r in results] == [_WALLPAPER_ID]
    assert results[0].rank == 1


def test_wallhaven_parse_respects_limit() -> None:
    p = WallhavenProvider()
    payload = _envelope([_WALLPAPER, _NSFW, _SPARSE])
    assert len(p._parse(payload, limit=2).results) == 2
    assert len(p._parse(payload).results) == 3


def test_wallhaven_parse_empty_and_malformed() -> None:
    p = WallhavenProvider()
    assert p._parse(_envelope([])).results == []
    assert p._parse({}).results == []
    assert p._parse({"data": "nope"}).results == []
    assert p._parse({"data": [1, 2, 3]}).results == []
    assert p._parse({"error": "Not Found"}).results == []
    assert p._parse([1, 2, 3]).results == []
    assert p._parse(None).results == []


def test_wallhaven_parse_ignores_odd_field_types() -> None:
    p = WallhavenProvider()
    payload = _envelope(
        [
            {
                "id": "  odd  ",
                "url": 42,
                "resolution": 5,
                "dimension_x": True,
                "dimension_y": "1080",
                "views": "many",
                "favorites": True,
                "file_size": "big",
                "colors": ["#fff", 7, ""],
                "created_at": "",
            }
        ],
        total=None,
    )
    r = p._parse(payload).results[0]

    assert r.title == "Wallhaven odd"
    assert r.url == "https://wallhaven.cc/w/odd"
    assert r.snippet == "#fff"
    assert r.published_date is None
    assert r.extra["width"] is None
    assert r.extra["height"] is None
    assert r.extra["file_size"] is None
    assert r.extra["colors"] == ["#fff"]


def test_wallhaven_helpers() -> None:
    from metasearchmcp.providers.wallhaven import (
        _clean,
        _human_size,
        _int,
        _label,
        _resolution,
        _strings,
        _thumbs,
    )

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _int(10116) == 10116
    assert _int(True) is None
    assert _int("10116") is None
    assert _strings(["#fff", 7, "", "#000"]) == ["#fff", "#000"]
    assert _strings("nope") == []
    assert _label("sfw") == "Sfw"
    assert _label("nsfw") == "NSFW"
    assert _label("people") == "People"
    assert _label(None) == ""
    assert _resolution({"resolution": " 1920x1080 "}) == "1920x1080"
    assert _resolution({"dimension_x": 100, "dimension_y": 200}) == "100x200"
    assert _resolution({"dimension_x": 100}) == ""
    assert _resolution({}) == ""
    assert _human_size(292334) == "285 KB"
    assert _human_size(2594101) == "2.5 MB"
    assert _human_size(1023) == "1023 B"
    assert _human_size(0) == "0 B"
    assert _human_size(-1) == ""
    assert _human_size(True) == ""
    assert _human_size("nope") == ""
    assert _thumbs({"original": " https://x/o.jpg ", "small": ""}) == {
        "original": "https://x/o.jpg"
    }
    assert _thumbs("nope") == {}


async def test_wallhaven_search_sends_expected_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope([_WALLPAPER, _NSFW]))
    )

    result = await WallhavenProvider().search(
        "anime",
        SearchParams(num_results=5),
    )

    assert route.called
    params = route.calls[0].request.url.params
    assert params["q"] == "anime"
    assert params["categories"] == "111"
    assert params["purity"] == "100"
    assert params["sorting"] == "relevance"
    assert params["order"] == "desc"
    assert params["page"] == "1"

    assert [r.extra["wallhaven_id"] for r in result.results] == [
        _WALLPAPER_ID,
        "lyd9gp",
    ]


async def test_wallhaven_search_requests_unrestricted_purity(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope([_WALLPAPER]))
    )

    await WallhavenProvider().search("anime", SearchParams(safe_search=False))

    assert route.calls[0].request.url.params["purity"] == "111"


async def test_wallhaven_search_caps_limit_to_api_maximum(respx_mock) -> None:
    records = [dict(_WALLPAPER, id=f"id{n}") for n in range(30)]
    respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope(records))
    )

    provider = WallhavenProvider()
    provider._max_results = 1000
    result = await provider.search("anime", SearchParams(num_results=50))
    # Wallhaven serves at most 24 wallpapers per page.
    assert len(result.results) == 24

    provider._max_results = 1
    result = await provider.search("anime", SearchParams(num_results=50))
    assert len(result.results) == 1


async def test_wallhaven_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT)

    result = await WallhavenProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_wallhaven_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(429))

    with pytest.raises(httpx.HTTPStatusError):
        await WallhavenProvider().search("anime", SearchParams())
