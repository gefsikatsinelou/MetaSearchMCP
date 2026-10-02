"""Unit tests for the dictionaryapi.dev English dictionary provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.dictionaryapi import DictionaryApiProvider

_WORD_URL = "https://api.dictionaryapi.dev/api/v2/entries/en/serendipity"

_ENTRY = {
    "word": "serendipity",
    "phonetic": "/ser-uh n-DIP-i-tee/",
    "phonetics": [
        {"text": "/ser-uh n-DIP-i-tee/", "audio": ""},
        {
            "text": "/ser-uh n-DIP-i-tee/",
            "audio": "https://api.dictionaryapi.dev/media/pronunciations/en/x-us.mp3",
        },
    ],
    "meanings": [
        {
            "partOfSpeech": "noun",
            "definitions": [
                {
                    "definition": "A combination of events by chance.",
                    "example": "A fortunate serendipity.",
                    "synonyms": ["chance", "luck"],
                    "antonyms": ["Murphy's law"],
                },
                {"definition": "An unsought discovery made by accident."},
            ],
        }
    ],
    "sourceUrls": ["https://en.wiktionary.org/wiki/serendipity"],
}


def _provider() -> DictionaryApiProvider:
    """Return a fresh provider instance for each test."""
    return DictionaryApiProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "dictionaryapi"
    assert p.tags == ["reference", "language"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "dictionaryapi" in registry
    assert registry["dictionaryapi"].tags == ["reference", "language"]


@pytest.mark.asyncio
async def test_search_builds_one_result_per_definition(respx_mock) -> None:
    respx_mock.get(_WORD_URL).mock(
        return_value=respx.MockResponse(200, json=[_ENTRY]),
    )

    result = await _provider().search("serendipity", SearchParams(num_results=10))

    assert [r.title for r in result.results] == ["serendipity", "serendipity"]
    first = result.results[0]

    assert first.url == "https://en.wiktionary.org/wiki/serendipity"
    assert first.source == "dictionaryapi.dev"
    assert first.provider == "dictionaryapi"
    assert first.rank == 1
    assert first.snippet == (
        "noun: A combination of events by chance. (e.g. A fortunate serendipity.)"
    )
    assert first.extra == {
        "part_of_speech": "noun",
        "example": "A fortunate serendipity.",
        "phonetic": "/ser-uh n-DIP-i-tee/",
        "audio": "https://api.dictionaryapi.dev/media/pronunciations/en/x-us.mp3",
        "synonyms": ["chance", "luck"],
        "antonyms": ["Murphy's law"],
    }
    # Second sense has no example or synonyms.
    second = result.results[1]
    assert second.rank == 2
    assert second.extra["example"] is None
    assert second.snippet == "noun: An unsought discovery made by accident."


@pytest.mark.asyncio
async def test_search_falls_back_to_wiktionary_url(respx_mock) -> None:
    entry = dict(_ENTRY)
    entry.pop("sourceUrls")
    respx_mock.get(_WORD_URL).mock(
        return_value=respx.MockResponse(200, json=[entry]),
    )

    result = await _provider().search("serendipity", SearchParams(num_results=10))

    assert result.results[0].url == "https://en.wiktionary.org/wiki/serendipity"


def test_phonetic_falls_back_to_phonetics_list() -> None:
    entry = {
        "word": "cat",
        "phonetics": [{"text": "/kæt/", "audio": ""}],
        "meanings": [],
    }
    assert _provider()._phonetic(entry) == "/kæt/"


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    respx_mock.get(_WORD_URL).mock(
        return_value=respx.MockResponse(200, json=[_ENTRY]),
    )

    result = await _provider().search("serendipity", SearchParams(num_results=1))

    assert len(result.results) == 1
    assert result.results[0].rank == 1


@pytest.mark.asyncio
async def test_search_skips_definitions_without_text(respx_mock) -> None:
    payload = [
        {
            "word": "x",
            "meanings": [
                {"partOfSpeech": "noun", "definitions": [{}, {"definition": "  "}]},
            ],
        },
    ]
    respx_mock.get("https://api.dictionaryapi.dev/api/v2/entries/en/x").mock(
        return_value=respx.MockResponse(200, json=payload),
    )

    result = await _provider().search("x", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_WORD_URL).mock(
        return_value=respx.MockResponse(200, json=[_ENTRY]),
    )

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_missing_word_returns_empty(respx_mock) -> None:
    respx_mock.get(_WORD_URL).mock(return_value=respx.MockResponse(404))

    result = await _provider().search("serendipity", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        "not a list",
        {"title": "No Definitions Found"},
        [None, "x", 3, {"word": "  "}],
        [],
    ],
)
async def test_search_handles_unexpected_payload_shapes(respx_mock, payload) -> None:
    respx_mock.get(_WORD_URL).mock(
        return_value=respx.MockResponse(200, json=payload),
    )

    result = await _provider().search("serendipity", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_search_url_encodes_multiple_words(respx_mock) -> None:
    route = respx_mock.get(
        "https://api.dictionaryapi.dev/api/v2/entries/en/ice_cream",
    ).mock(return_value=respx.MockResponse(404))

    result = await _provider().search("ice cream", SearchParams(num_results=5))

    assert route.called
    assert result.results == []


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_WORD_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("serendipity", SearchParams(num_results=5))
