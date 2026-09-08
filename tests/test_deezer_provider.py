"""Unit tests for the Deezer music search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.deezer import DeezerProvider

_SEARCH_RESPONSE: dict[str, object] = {
    "data": [
        {
            "id": 136889400,
            "title": "Starboy",
            "link": "https://www.deezer.com/track/136889400",
            "duration": 230,
            "rank": 975897,
            "explicit_lyrics": True,
            "preview": "https://cdnt-preview.dzcdn.net/api/1/1/3/example.mp3",
            "type": "track",
            "artist": {
                "id": 4050205,
                "name": "The Weeknd",
                "link": "https://www.deezer.com/artist/4050205",
            },
            "album": {
                "id": 141757292,
                "title": "Starboy",
                "cover_medium": "https://cdn-images.dzcdn.net/images/cover/example/250x250.jpg",
            },
        },
        {
            "id": 69387296,
            "title": "Get Lucky",
            "link": "https://www.deezer.com/track/69387296",
            "duration": 369,
            "rank": 853110,
            "explicit_lyrics": False,
            "preview": "",
            "type": "track",
            "artist": {"id": 27, "name": "Daft Punk"},
            "album": {"id": 78803912, "title": "Random Access Memories"},
        },
        "junk",  # type: ignore[list-item]
        {"title": "orphan"},
        {"link": "https://www.deezer.com/track/1"},
    ]
}

_EMPTY_RESPONSE: dict[str, object] = {"data": []}


def _provider() -> DeezerProvider:
    return DeezerProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "deezer"
    assert p.tags == ["music", "media", "web"]
    assert "no API key required" in p.description


def test_parse_basic_hit_fields() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)

    assert len(result.results) == 2
    first = result.results[0]
    assert first.title == "Starboy · The Weeknd"
    assert first.url == "https://www.deezer.com/track/136889400"
    assert first.source == "deezer.com"
    assert first.provider == "deezer"
    assert first.rank == 1
    assert "Artist: The Weeknd" in first.snippet
    assert "Album: Starboy" in first.snippet
    assert "Duration: 3:50" in first.snippet
    assert "Explicit" in first.snippet
    assert first.extra["track_id"] == 136889400
    assert first.extra["artist"] == "The Weeknd"
    assert first.extra["artist_url"] == "https://www.deezer.com/artist/4050205"
    assert first.extra["album"] == "Starboy"
    assert first.extra["duration_seconds"] == 230
    assert first.extra["preview_url"].startswith("https://")
    assert first.extra["explicit_lyrics"] is True
    assert first.extra["deezer_rank"] == 975897


def test_parse_non_explicit_hit_without_preview() -> None:
    p = _provider()
    second = p._parse(_SEARCH_RESPONSE).results[1]
    assert second.title == "Get Lucky · Daft Punk"
    assert "Duration: 6:09" in second.snippet
    assert "Explicit" not in second.snippet
    assert second.extra["preview_url"] == ""
    assert second.extra["explicit_lyrics"] is False
    assert second.extra["artist_id"] == 27


def test_parse_skips_entries_without_title_or_url() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    # The "junk" string, the title-only dict, and the link-only dict are skipped.
    assert len(result.results) == 2


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []
    assert p._parse(None).results == []
    assert p._parse("junk").results == []
    assert p._parse({"data": "junk"}).results == []
    assert p._parse({"data": [{}]}).results == []


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse(_SEARCH_RESPONSE, limit=1).results) == 1


def test_parse_handles_missing_artist_and_album() -> None:
    p = _provider()
    payload = {
        "data": [
            {
                "id": 1,
                "title": "Ambient Piece",
                "link": "https://www.deezer.com/track/1",
            }
        ]
    }
    result = p._parse(payload)
    assert len(result.results) == 1
    hit = result.results[0]
    assert hit.title == "Ambient Piece"
    assert hit.extra["artist"] == ""
    assert hit.extra["album"] == ""
    assert hit.extra["duration_seconds"] == 0


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_gets_search_api(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.deezer.com/search").mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE)
    )

    p = _provider()
    result = await p.search("starboy", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].title == "Starboy · The Weeknd"
    call = respx_mock.calls[0]
    assert call.request.url.path == "/search"
    assert call.request.url.params["q"] == "starboy"
    assert call.request.url.params["limit"] == "5"
