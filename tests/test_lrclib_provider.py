"""Unit tests for the LRCLIB music lyrics search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.lrclib import LrclibProvider

_SAMPLE_RESPONSE: list[object] = [
    {
        "id": 33756008,
        "name": "Coldplay - Yellow",
        "trackName": "Yellow",
        "artistName": "Coldplay",
        "albumName": "Parachutes",
        "duration": 273.0,
        "instrumental": False,
        "hasWordSync": False,
        "plainLyrics": "Look at the stars\nLook how they shine for you\nAnd so on",
        "syncedLyrics": "[00:26.71] Look at the stars",
    },
    {
        # Instrumental: no album, unknown duration, no id -> falls back to the
        # search URL, and trackName already embeds the artist name.
        "trackName": "Coldplay - Yellow (Instrumental)",
        "artistName": "Coldplay",
        "duration": 0,
        "instrumental": True,
        "plainLyrics": None,
    },
    {
        # Missing both track and artist -> skipped entirely.
        "id": 5,
        "albumName": "Untitled",
    },
    "junk",
]

_EMPTY_RESPONSE: list[object] = []


def _provider() -> LrclibProvider:
    return LrclibProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "lrclib"
    assert p.tags == ["music", "media", "web"]
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "lrclib" in registry
    assert registry["lrclib"].tags == ["music", "media", "web"]


def test_parse_basic_fields() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, query="yellow")

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Yellow — Coldplay"
    assert r.url == "https://lrclib.net/tracks/33756008"
    assert r.provider == "lrclib"
    assert r.source == "lrclib.net"
    assert r.rank == 1
    assert "Artist: Coldplay" in r.snippet
    assert "Album: Parachutes" in r.snippet
    assert "Duration: 4:33" in r.snippet
    assert "Look at the stars" in r.snippet
    assert r.extra["track_id"] == 33756008
    assert r.extra["track"] == "Yellow"
    assert r.extra["artist"] == "Coldplay"
    assert r.extra["album"] == "Parachutes"
    assert r.extra["duration_seconds"] == 273.0
    assert r.extra["instrumental"] is False
    assert r.extra["has_synced_lyrics"] is True
    assert (
        r.extra["plain_lyrics"]
        == "Look at the stars Look how they shine for you And so on"
    )


def test_parse_instrumental_and_missing_id() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, query="coldplay")

    second = result.results[1]
    # trackName already contains the artist -> used verbatim as the title.
    assert second.title == "Coldplay - Yellow (Instrumental)"
    assert second.rank == 2
    # No track id -> links back to the LRCLIB search page for the query.
    assert second.url == "https://lrclib.net/search/coldplay"
    assert "Instrumental" in second.snippet
    assert "Duration" not in second.snippet
    assert second.extra["track_id"] is None
    assert second.extra["duration_seconds"] is None
    assert second.extra["instrumental"] is True
    assert second.extra["has_synced_lyrics"] is False
    assert second.extra["plain_lyrics"] is None


def test_parse_skips_record_without_link() -> None:
    # No id and no query -> no usable URL, so the record is dropped.
    assert _provider()._parse([{"trackName": "X", "artistName": "Y"}]).results == []


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse({}).results == []
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse("junk").results == []
    assert p._parse([42, None]).results == []


def test_parse_respects_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1
    assert result.results[0].title == "Yellow — Coldplay"


def test_duration_label_fallbacks() -> None:
    assert LrclibProvider._duration_label(None) == ""
    assert LrclibProvider._duration_label(0) == ""
    assert LrclibProvider._duration_label(59) == "0:59"
    assert LrclibProvider._duration_label(273) == "4:33"
    assert LrclibProvider._duration_label(3600) == "60:00"


def test_duration_normalisation() -> None:
    # LRCLIB reports unknown durations as 0 -> normalised to None.
    assert LrclibProvider._duration(0) is None
    assert LrclibProvider._duration(-3) is None
    assert LrclibProvider._duration(None) is None
    assert LrclibProvider._duration("273") is None
    assert LrclibProvider._duration(True) is None
    assert LrclibProvider._duration(273) == 273.0


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get("https://lrclib.net/api/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    result = await _provider().search("yellow", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "lrclib"
    assert len(respx_mock.calls) == 1
    request = respx_mock.calls[0].request
    assert request.url.params["q"] == "yellow"


@pytest.mark.asyncio
async def test_search_no_match(respx_mock) -> None:
    import respx

    respx_mock.get("https://lrclib.net/api/search").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    result = await _provider().search("zzzz", SearchParams(num_results=5))
    assert result.results == []
