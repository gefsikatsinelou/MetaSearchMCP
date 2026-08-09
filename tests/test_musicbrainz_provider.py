"""Unit tests for the MusicBrainz search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.musicbrainz import MusicBrainzProvider, _format_length


def _sample_response() -> dict:
    return {
        "created": "2026-01-01T00:00:00.000Z",
        "count": 13453,
        "offset": 0,
        "recordings": [
            {
                "id": "ef1cf9c7-e4bc-416b-9ead-d76a5d149978",
                "score": 100,
                "title": "Radiohead",
                "length": 307560,
                "artist-credit": [
                    {
                        "name": "Miss Mister",
                        "artist": {"id": "x", "name": "Miss Mister"},
                    },
                ],
                "first-release-date": "2008",
            },
            {
                "id": "b7b2b6e0-3c9a-4f5e-8f2a-2a9c4f2b7f11",
                "score": 87,
                "title": "Paranoid Android",
                "length": 383000,
                "artist-credit": [
                    {
                        "name": "Radiohead",
                        "artist": {"id": "y", "name": "Radiohead"},
                    },
                ],
                "first-release-date": "1997-05-28",
                "disambiguation": "full length version",
            },
            {
                "id": "",
                "title": "No id, must be skipped",
            },
            {
                "id": "c0ffee00-0000-0000-0000-000000000000",
                "title": "",
                "artist-credit": [],
            },
            "not-a-dict",
            None,
        ],
    }


def test_parse_basic():
    p = MusicBrainzProvider()
    result = p._parse(_sample_response())

    assert len(result.results) == 2  # invalid items are skipped
    r = result.results[0]
    assert r.title == "Radiohead"
    assert (
        r.url
        == "https://musicbrainz.org/recording/ef1cf9c7-e4bc-416b-9ead-d76a5d149978"
    )
    assert r.provider == "musicbrainz"
    assert r.source == "musicbrainz.org"
    assert r.rank == 1
    assert "Miss Mister" in r.snippet
    assert "first released 2008" in r.snippet
    assert "5:07" in r.snippet  # 307560 ms -> 5:07
    assert r.extra["score"] == 100.0
    assert r.extra["artists"] == "Miss Mister"
    assert r.extra["first_release_date"] == "2008"
    assert r.extra["length"] == "5:07"


def test_parse_second_result_rank_and_disambiguation():
    p = MusicBrainzProvider()
    result = p._parse(_sample_response())
    r = result.results[1]
    assert r.rank == 2
    assert r.title == "Paranoid Android"
    assert r.extra["disambiguation"] == "full length version"
    assert r.extra["score"] == 87.0


def test_parse_empty():
    p = MusicBrainzProvider()
    result = p._parse({})
    assert result.results == []

    result = p._parse({"recordings": []})
    assert result.results == []


def test_format_length():
    assert _format_length(None) is None
    assert _format_length(0) is None
    assert _format_length(307560) == "5:07"
    assert _format_length(383000) == "6:23"
    assert _format_length(3661000) == "1:01:01"


def test_is_available():
    """Keyless provider is always available."""
    assert MusicBrainzProvider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock):
    import respx

    respx_mock.get(
        "https://musicbrainz.org/ws/2/recording",
        params={"query": "radiohead", "fmt": "json", "limit": "5"},
    ).mock(
        return_value=respx.MockResponse(200, json=_sample_response()),
    )

    p = MusicBrainzProvider()
    result = await p.search("radiohead", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "musicbrainz"
    assert result.results[0].title == "Radiohead"
    assert result.results[0].url.startswith("https://musicbrainz.org/recording/")
