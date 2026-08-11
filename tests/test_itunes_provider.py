"""Unit tests for the iTunes (podcast) search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.itunes import ITunesProvider


def _sample_response() -> dict:
    return {
        "resultCount": 3,
        "results": [
            {
                "wrapperType": "track",
                "kind": "podcast",
                "collectionId": 73331728,
                "collectionName": "The Daily",
                "artistName": "The New York Times",
                "collectionViewUrl": (
                    "https://podcasts.apple.com/us/podcast/the-daily/id73331728"
                ),
                "artworkUrl100": "https://example.com/artwork/the-daily.jpg",
                "feedUrl": "https://feeds.simplecast.com/54nAGcIl",
                "trackCount": 1600,
                "primaryGenreName": "News",
                "releaseDate": "2026-08-10T04:00:00Z",
            },
            {
                "wrapperType": "track",
                "kind": "podcast",
                "collectionId": 73331728,
                "collectionName": "Hard Fork",
                "artistName": "The New York Times",
                "collectionViewUrl": (
                    "https://podcasts.apple.com/us/podcast/hard-fork/id73331728"
                ),
                "feedUrl": "https://feeds.simplecast.com/hard-fork",
                "trackCount": 200,
                "primaryGenreName": "Technology",
                "releaseDate": "2026-08-09T04:00:00Z",
            },
            {
                "wrapperType": "track",
                "kind": "podcast",
                "collectionName": "",
                "collectionViewUrl": "https://podcasts.apple.com/us/podcast/x",
            },
            "not-a-dict",
            None,
        ],
    }


def test_parse_basic():
    p = ITunesProvider()
    result = p._parse(_sample_response())

    # Invalid items (missing title/url, non-dict) are skipped.
    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "The Daily"
    assert r.url == "https://podcasts.apple.com/us/podcast/the-daily/id73331728"
    assert r.provider == "itunes"
    assert r.source == "podcasts.apple.com"
    assert r.rank == 1
    assert "The New York Times" in r.snippet
    assert "News" in r.snippet
    assert r.published_date == "2026-08-10"
    assert r.extra["artist"] == "The New York Times"
    assert r.extra["genre"] == "News"
    assert r.extra["feed_url"] == "https://feeds.simplecast.com/54nAGcIl"
    assert r.extra["artwork_url"] == "https://example.com/artwork/the-daily.jpg"
    assert r.extra["episode_count"] == 1600


def test_parse_second_result_rank_and_genre():
    p = ITunesProvider()
    result = p._parse(_sample_response())
    r = result.results[1]
    assert r.rank == 2
    assert r.title == "Hard Fork"
    assert r.extra["genre"] == "Technology"


def test_parse_empty():
    p = ITunesProvider()
    result = p._parse({})
    assert result.results == []

    result = p._parse({"results": []})
    assert result.results == []


def test_parse_missing_optional_fields():
    p = ITunesProvider()
    data = {
        "results": [
            {
                "wrapperType": "track",
                "kind": "podcast",
                "collectionName": "Minimal Show",
                "collectionViewUrl": "https://podcasts.apple.com/us/podcast/minimal",
            },
        ],
    }
    result = p._parse(data)
    r = result.results[0]
    assert r.title == "Minimal Show"
    assert r.snippet == ""
    assert r.published_date is None
    assert r.extra == {}


def test_is_available():
    """Keyless provider is always available."""
    assert ITunesProvider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock):
    import respx

    respx_mock.get(
        "https://itunes.apple.com/search",
        params={
            "term": "the daily",
            "media": "podcast",
            "limit": "5",
            "country": "US",
        },
    ).mock(
        return_value=respx.MockResponse(200, json=_sample_response()),
    )

    p = ITunesProvider()
    result = await p.search("the daily", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "itunes"
    assert result.results[0].title == "The Daily"
    assert result.results[0].url.startswith("https://podcasts.apple.com/")
