"""Unit tests for the Dailymotion video search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.providers.dailymotion import DailymotionProvider

_SAMPLE_RESPONSE = {
    "page": 1,
    "limit": 3,
    "explicit": False,
    "total": 2,
    "has_more": False,
    "list": [
        {
            "id": "x3733ir",
            "title": "PYTHON PROGRAMMING BASIC",
            "url": "https://www.dailymotion.com/video/x3733ir",
            "description": "A gentle introduction to Python.",
            "duration": 883,
            "created_time": 1442425696,
            "owner.screenname": "Learn Computer Science in an Easy Way",
            "thumbnail_360_url": "https://s1.dmcdn.net/v/BXOUJ1g50M8GhYETM/x360",
            "views_total": 120,
        },
        {
            "id": "x16i5jq",
            "title": "No URL Video",
            "url": "",
            "description": "Should be skipped.",
            "duration": 146,
            "created_time": 1382921063,
            "owner.screenname": "Shaban Ismail",
            "thumbnail_360_url": "",
            "views_total": 2,
        },
        {
            "id": "x99zzzz",
            "title": "",
            "url": "https://www.dailymotion.com/video/x99zzzz",
            "description": "Missing title should be skipped.",
            "duration": 10,
            "created_time": None,
            "owner.screenname": "",
            "thumbnail_360_url": "",
            "views_total": 0,
        },
    ],
}

_EMPTY_RESPONSE = {
    "page": 1,
    "limit": 10,
    "explicit": False,
    "total": 0,
    "has_more": False,
    "list": [],
}


def test_dailymotion_parse_basic():
    p = DailymotionProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "PYTHON PROGRAMMING BASIC"
    assert r.url == "https://www.dailymotion.com/video/x3733ir"
    assert "gentle introduction" in r.snippet
    assert "Duration: 14:43" in r.snippet
    assert "Views: 120" in r.snippet
    assert "By: Learn Computer Science in an Easy Way" in r.snippet
    assert r.source == "dailymotion.com"
    assert r.provider == "dailymotion"
    assert r.rank == 1
    assert r.published_date == "2015-09-16"
    assert r.extra["video_id"] == "x3733ir"
    assert r.extra["owner"] == "Learn Computer Science in an Easy Way"
    assert r.extra["thumbnail_url"] == "https://s1.dmcdn.net/v/BXOUJ1g50M8GhYETM/x360"
    assert r.extra["duration_seconds"] == 883
    assert r.extra["duration"] == "14:43"
    assert r.extra["views"] == 120


def test_dailymotion_parse_skips_missing_url_or_title():
    p = DailymotionProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    assert all(r.url for r in result.results)
    assert all(r.title for r in result.results)


def test_dailymotion_parse_empty():
    p = DailymotionProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_dailymotion_parse_missing_keys():
    p = DailymotionProvider()
    result = p._parse(
        {
            "list": [
                {
                    "id": "x1",
                    "title": "Lonely",
                    "url": "https://www.dailymotion.com/video/x1",
                }
            ]
        }
    )
    r = result.results[0]
    assert r.snippet == ""
    assert r.published_date is None
    assert r.extra["duration"] == ""
    assert r.extra["views"] == 0
    assert r.extra["owner"] == ""
    assert r.extra["thumbnail_url"] == ""


def test_dailymotion_format_duration():
    assert DailymotionProvider._format_duration(0) == ""
    assert DailymotionProvider._format_duration(None) == ""
    assert DailymotionProvider._format_duration("bad") == ""
    assert DailymotionProvider._format_duration(45) == "0:45"
    assert DailymotionProvider._format_duration(883) == "14:43"
    assert DailymotionProvider._format_duration(3661) == "1:01:01"


def test_dailymotion_published_date():
    assert DailymotionProvider._published_date(None) is None
    assert DailymotionProvider._published_date("") is None
    assert DailymotionProvider._published_date("bad") is None
    assert DailymotionProvider._published_date(1442425696) == "2015-09-16"


def test_dailymotion_is_available():
    """Keyless provider is always available."""
    assert DailymotionProvider().is_available() is True


@pytest.mark.asyncio
async def test_dailymotion_search_builds_query(respx_mock):
    """The search method hits the videos endpoint and parses the response."""
    import respx

    respx_mock.get("https://api.dailymotion.com/videos").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    from metasearchmcp.contracts import SearchParams

    p = DailymotionProvider()
    result = await p.search("python", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "dailymotion"
