"""Unit tests for the LibriVox audiobook provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.librivox import LibriVoxProvider

_ENDPOINT = "https://librivox.org/api/feed/audiobooks/"

_PAYLOAD = {
    "books": [
        {
            "id": "47",
            "title": "Count of Monte Cristo",
            "authors": [
                {
                    "id": "431",
                    "first_name": "Alexandre",
                    "last_name": "Dumas",
                    "dob": "1802",
                    "dod": "1870",
                },
            ],
            "description": "<i>The Count of Monte Cristo</i> is an adventure novel.",
            "language": "English",
            "copyright_year": "1844",
            "num_sections": "128",
            "totaltime": "49:43:15",
            "totaltimesecs": 178995,
            "url_librivox": (
                "https://librivox.org/the-count-of-monte-cristo-by-alexandre-dumas/"
            ),
            "url_text_source": "https://www.gutenberg.org/etext/1184",
            "url_rss": "https://librivox.org/rss/47",
            "url_zip_file": "https://archive.org/compress/count_monte_cristo.zip",
            "url_project": "https://en.wikipedia.org/wiki/Count_of_Monte_Cristo",
        },
        {
            "id": "999",
            "title": "No Page Title",
            "url_librivox": "",
            "totaltimesecs": "not-a-number",
        },
        {"id": "1000", "title": "", "url_librivox": "https://librivox.org/x/"},
        "not-a-mapping",
    ],
}


def _mock(respx_mock, payload: object = _PAYLOAD):
    """Mock the LibriVox search endpoint with *payload*."""
    return respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=payload),
    )


def _provider() -> LibriVoxProvider:
    """Return a fresh provider instance for each test."""
    return LibriVoxProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "librivox"
    assert p.tags == ["books", "media", "audio", "knowledge"]
    assert "No API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "librivox" in registry
    assert registry["librivox"].tags == ["books", "media", "audio", "knowledge"]


@pytest.mark.asyncio
async def test_search_builds_structured_result(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("monte cristo", SearchParams(num_results=10))
    book = result.results[0]

    assert book.title == "Count of Monte Cristo"
    assert book.url == (
        "https://librivox.org/the-count-of-monte-cristo-by-alexandre-dumas/"
    )
    assert book.source == "librivox.org"
    assert book.provider == "librivox"
    assert book.rank == 1
    assert book.snippet == (
        "By: Alexandre Dumas | Language: English | Year: 1844 | "
        "Duration: 49:43:15 | 128 sections"
    )
    assert book.extra == {
        "id": "47",
        "authors": ["Alexandre Dumas"],
        "language": "English",
        "copyright_year": "1844",
        "num_sections": "128",
        "totaltime": "49:43:15",
        "totaltimesecs": 178995,
        "description": "The Count of Monte Cristo is an adventure novel.",
        "url_text_source": "https://www.gutenberg.org/etext/1184",
        "url_rss": "https://librivox.org/rss/47",
        "url_zip_file": "https://archive.org/compress/count_monte_cristo.zip",
        "url_project": "https://en.wikipedia.org/wiki/Count_of_Monte_Cristo",
    }


@pytest.mark.asyncio
async def test_search_skips_incomplete_and_malformed_entries(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("monte cristo", SearchParams(num_results=10))

    assert [r.title for r in result.results] == ["Count of Monte Cristo"]
    assert [r.rank for r in result.results] == [1]


@pytest.mark.asyncio
async def test_search_coerces_non_integer_duration(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("monte cristo", SearchParams(num_results=10))

    assert result.results[0].extra["totaltimesecs"] == 178995


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    _mock(
        respx_mock,
        {
            "books": [
                {"id": "1", "title": "A", "url_librivox": "https://librivox.org/a/"},
                {"id": "2", "title": "B", "url_librivox": "https://librivox.org/b/"},
            ],
        },
    )

    result = await _provider().search("a", SearchParams(num_results=1))

    assert [r.title for r in result.results] == ["A"]


@pytest.mark.asyncio
async def test_search_sends_query_params(respx_mock) -> None:
    route = _mock(respx_mock)

    await _provider().search("monte cristo", SearchParams(num_results=5))

    params = route.calls.last.request.url.params
    assert params["q"] == "monte cristo"
    assert params["format"] == "json"
    assert params["limit"] == "5"


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    route = _mock(respx_mock)

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_handles_unexpected_payload_shapes(respx_mock) -> None:
    for payload in (
        ["not", "a", "mapping"],
        {},
        {"books": None},
        {"books": "nope"},
        {"error": "Audiobooks could not be found"},
    ):
        respx_mock.get(_ENDPOINT).mock(
            return_value=respx.MockResponse(200, json=payload),
        )
        result = await _provider().search("monte cristo", SearchParams(num_results=5))
        assert result.results == []


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("monte cristo", SearchParams(num_results=5))
