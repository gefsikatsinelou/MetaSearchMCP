"""Unit tests for the PeerTube video search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.providers.peertube import PeerTubeProvider

_SAMPLE_RESPONSE = {
    "total": 2,
    "data": [
        {
            "name": "Python for Beginners",
            "url": "https://tube.example.org/videos/watch/abc123",
            "truncatedDescription": "A gentle introduction to Python.",
            "duration": 133,
            "views": 20,
            "likes": 3,
            "publishedAt": "2026-05-31T14:46:03.923Z",
            "thumbnailPath": "/lazy-static/thumbnails/thumb1.jpg",
            "nsfw": False,
            "category": {"id": 1, "label": "Science & Technology"},
            "language": {"id": "en", "label": "English"},
            "channel": {
                "name": "teach",
                "displayName": "Teach Channel",
                "url": "https://tube.example.org/video-channels/teach",
            },
            "account": {
                "name": "alice",
                "displayName": "Alice",
                "url": "https://tube.example.org/accounts/alice",
            },
        },
        {
            "name": "No URL Video",
            "url": "",
            "duration": 58,
            "views": 22,
            "likes": 0,
        },
    ],
}

_EMPTY_RESPONSE = {"total": 0, "data": []}


def test_peertube_parse_basic():
    p = PeerTubeProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Python for Beginners"
    assert r.url == "https://tube.example.org/videos/watch/abc123"
    assert "gentle introduction" in r.snippet
    assert "Duration: 2:13" in r.snippet
    assert "Views: 20" in r.snippet
    assert r.source == "peertube.tv"
    assert r.provider == "peertube"
    assert r.rank == 1
    assert r.published_date == "2026-05-31"
    assert r.extra["channel"] == "Teach Channel"
    assert r.extra["author"] == "Alice"
    assert r.extra["views"] == 20
    assert r.extra["likes"] == 3
    assert r.extra["category"] == "Science & Technology"
    assert r.extra["language"] == "English"
    assert r.extra["nsfw"] is False


def test_peertube_parse_skips_video_without_url():
    p = PeerTubeProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    assert all(r.url for r in result.results)


def test_peertube_parse_empty():
    p = PeerTubeProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_peertube_parse_missing_keys():
    p = PeerTubeProvider()
    result = p._parse({"data": [{"name": "Lonely", "url": "https://x.example/v"}]})
    r = result.results[0]
    assert r.snippet == ""
    assert r.published_date is None
    assert r.extra["duration"] == ""
    assert r.extra["views"] == 0
    assert r.extra["channel"] == ""
    assert r.extra["author"] == ""


def test_peertube_format_duration():
    assert PeerTubeProvider._format_duration(0) == ""
    assert PeerTubeProvider._format_duration(None) == ""
    assert PeerTubeProvider._format_duration("bad") == ""
    assert PeerTubeProvider._format_duration(45) == "0:45"
    assert PeerTubeProvider._format_duration(133) == "2:13"
    assert PeerTubeProvider._format_duration(3661) == "1:01:01"


def test_peertube_absolute_thumbnail():
    assert (
        PeerTubeProvider._absolute_thumbnail("/lazy-static/thumb1.jpg")
        == "https://peertube.tv/lazy-static/thumb1.jpg"
    )
    assert (
        PeerTubeProvider._absolute_thumbnail("https://cdn.example/x.jpg")
        == "https://cdn.example/x.jpg"
    )
    assert PeerTubeProvider._absolute_thumbnail("") == ""
    assert PeerTubeProvider._absolute_thumbnail(None) == ""


def test_peertube_is_available():
    """Keyless provider is always available."""
    assert PeerTubeProvider().is_available() is True


@pytest.mark.asyncio
async def test_peertube_search_builds_query(respx_mock):
    """The search method hits the videos endpoint and parses the response."""
    import respx

    respx_mock.get("https://peertube.tv/api/v1/videos").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    from metasearchmcp.contracts import SearchParams

    p = PeerTubeProvider()
    result = await p.search("python", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "peertube"
