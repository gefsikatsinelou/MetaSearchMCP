"""Unit tests for the Audius music provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.audius import AudiusProvider

_API_URL = "https://api.audius.co/v1/tracks/search"

_TRACKS_RESPONSE: dict[str, object] = {
    "data": [
        {
            "id": "O6bw9pR",
            "track_id": 370899,
            "title": "Stars In The Sky - Lofi Beats",
            "permalink": "/Lofibeat/stars-in-the-sky-lofi-beats-370899",
            "slug": "stars-in-the-sky-lofi-beats-370899",
            "user": {"id": "abc123", "name": "Lofibeat", "handle": "Lofibeat"},
            "genre": "Hip-Hop/Rap",
            "mood": "Peaceful",
            "duration": 71,
            "play_count": 53132,
            "favorite_count": 1997,
            "repost_count": 1269,
            "is_streamable": True,
            "is_downloadable": False,
            "license": "All rights reserved",
            "tags": "stars,sky,lofi,,chillhop",
            "artwork": {
                "150x150": "https://cdn.example/150.jpg",
                "480x480": "https://cdn.example/480.jpg",
                "1000x1000": "https://cdn.example/1000.jpg",
            },
            "description": "Stars In The Sky.. Time To Chill...",
            "release_date": "2021-04-20T08:00:10Z",
        },
        {
            # No permalink -> URL rebuilt from handle + slug; not streamable,
            # so no stream URL; artist falls back to the handle.
            "id": "am4MGow",
            "track_id": 2,
            "title": "Dark Piano",
            "permalink": "",
            "slug": "dark-piano-42",
            "user": {"name": "", "handle": "br2356"},
            "genre": "",
            "mood": "",
            "duration": 3605,
            "play_count": 0,
            "is_streamable": False,
            "tags": "",
            "artwork": {},
            "description": "",
            "release_date": "",
        },
        # Empty title -> skipped.
        {"id": "x", "title": "", "permalink": "/a/b"},
        # Title but no permalink/handle/slug -> no page URL -> skipped.
        {"id": "y", "title": "Orphan", "permalink": "", "user": {}, "slug": ""},
        "junk",
        None,
    ],
}


def _provider() -> AudiusProvider:
    return AudiusProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "audius"
    assert p.tags == ["music", "media", "web"]
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "audius" in registry
    assert registry["audius"].tags == ["music", "media", "web"]


def test_parse_maps_track_fields() -> None:
    result = _provider()._parse(_TRACKS_RESPONSE, limit=10)

    assert [r.title for r in result.results] == [
        "Stars In The Sky - Lofi Beats · Lofibeat",
        "Dark Piano · br2356",
    ]

    first = result.results[0]
    assert first.rank == 1
    assert first.url == (
        "https://audius.co/Lofibeat/stars-in-the-sky-lofi-beats-370899"
    )
    assert first.source == "audius.co"
    assert first.provider == "audius"
    assert first.published_date == "2021-04-20"
    assert "Stars In The Sky" in first.snippet
    assert "Artist: Lofibeat" in first.snippet
    assert "Genre: Hip-Hop/Rap" in first.snippet
    assert "Mood: Peaceful" in first.snippet
    assert "Duration: 1:11" in first.snippet
    assert "Plays: 53,132" in first.snippet
    assert first.extra["track_id"] == "O6bw9pR"
    assert first.extra["numeric_id"] == 370899
    assert first.extra["artist"] == "Lofibeat"
    assert first.extra["artist_handle"] == "Lofibeat"
    assert first.extra["artist_id"] == "abc123"
    assert first.extra["genre"] == "Hip-Hop/Rap"
    assert first.extra["mood"] == "Peaceful"
    assert first.extra["duration_seconds"] == 71
    assert first.extra["play_count"] == 53132
    assert first.extra["favorite_count"] == 1997
    assert first.extra["repost_count"] == 1269
    assert first.extra["tags"] == ["stars", "sky", "lofi", "chillhop"]
    assert first.extra["artwork_url"] == "https://cdn.example/480.jpg"
    assert first.extra["stream_url"] == (
        "https://api.audius.co/v1/tracks/O6bw9pR/stream?app_name=MetaSearchMCP"
    )
    assert first.extra["is_streamable"] is True
    assert first.extra["license"] == "All rights reserved"


def test_parse_rebuilds_url_and_skips_unstreamable_stream() -> None:
    result = _provider()._parse(_TRACKS_RESPONSE, limit=10)

    second = result.results[1]
    assert second.rank == 2
    assert second.url == "https://audius.co/br2356/dark-piano-42"
    assert second.extra["artist"] == "br2356"
    assert second.extra["duration_seconds"] == 3605
    assert "Duration: 1:00:05" in second.snippet
    assert second.extra["artwork_url"] == ""
    assert second.extra["stream_url"] == ""
    assert second.extra["is_streamable"] is False
    assert second.published_date is None


def test_parse_handles_junk_and_limits() -> None:
    assert _provider()._parse("junk", limit=5).results == []
    assert _provider()._parse({}, limit=5).results == []
    assert _provider()._parse({"data": "junk"}, limit=5).results == []

    limited = _provider()._parse(_TRACKS_RESPONSE, limit=1)
    assert len(limited.results) == 1
    assert limited.results[0].rank == 1


def test_snippet_is_truncated_to_shared_limit() -> None:
    data = {
        "data": [
            {
                "id": "long",
                "title": "Long Track",
                "permalink": "/artist/long-track",
                "user": {"name": "Artist", "handle": "artist"},
                "genre": "y" * 100,
                "duration": 30,
                "description": "word " * 200,
                "is_streamable": True,
            },
        ],
    }
    result = _provider()._parse(data, limit=5)
    snippet = result.results[0].snippet
    assert len(snippet) <= 400
    assert snippet.startswith("word word")


@pytest.mark.asyncio
async def test_search_sends_query_and_limit(respx_mock) -> None:
    import respx

    route = respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_TRACKS_RESPONSE),
    )

    result = await _provider().search("lofi beats", SearchParams(num_results=4))

    assert [r.title for r in result.results] == [
        "Stars In The Sky - Lofi Beats · Lofibeat",
        "Dark Piano · br2356",
    ]
    params = route.calls[0].request.url.params
    assert params["query"] == "lofi beats"
    assert params["app_name"] == "MetaSearchMCP"
    assert params["limit"] == "4"


@pytest.mark.asyncio
async def test_search_with_blank_query_returns_empty(respx_mock) -> None:
    import respx

    route = respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_TRACKS_RESPONSE),
    )

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_tolerates_non_json_response(respx_mock) -> None:
    import respx

    respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(
            200,
            text="<html><body>maintenance</body></html>",
            headers={"Content-Type": "text/html"},
        ),
    )

    result = await _provider().search("lofi", SearchParams(num_results=5))

    assert result.results == []
