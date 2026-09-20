"""Unit tests for the Urban Dictionary slang search provider."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.urbandictionary import UrbanDictionaryProvider

_DEFINE = "https://api.urbandictionary.com/v0/define"
_AUTOCOMPLETE = "https://api.urbandictionary.com/v0/autocomplete"

_RIZZ: dict[str, Any] = {
    "author": "bro got no rizz",
    "current_vote": "",
    "defid": 17115763,
    "definition": (
        "Another [word] for spitting [game]/how good you are with "
        "pulling and sustaining [bitches]."
    ),
    "example": "Person 1: are you from Tennessee [cuz] u the only ten i [see]\r\n",
    "permalink": "https://www.urbandictionary.com/define.php?term=Rizz&defid=17115763",
    "thumbs_down": 12,
    "thumbs_up": 345,
    "word": "Rizz",
    "written_on": "2022-03-31T10:36:17.000Z",
}

# Minimal record: only a headword and a definition.
_BARE: dict[str, Any] = {"word": "Bare", "definition": "Minimal   entry\n"}

# Legacy record without a permalink, a defid or a submission date.
_LEGACY: dict[str, Any] = {"word": "Test Term", "definition": "A [legacy] entry"}


def _envelope(entries: list[Any]) -> dict[str, Any]:
    """Wrap *entries* in an Urban Dictionary define response envelope."""
    return {"list": entries}


def test_urbandictionary_name_tags_and_availability() -> None:
    p = UrbanDictionaryProvider()
    assert p.name == "urbandictionary"
    assert p.tags == ["web", "reference", "language", "social"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_urbandictionary_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "urbandictionary" in registry
    assert registry["urbandictionary"].tags == [
        "web",
        "reference",
        "language",
        "social",
    ]


def test_urbandictionary_parse_definition_record() -> None:
    p = UrbanDictionaryProvider()
    result = p._parse(_envelope([_RIZZ]), limit=5)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Rizz"
    assert (
        r.url == "https://www.urbandictionary.com/define.php?term=Rizz&defid=17115763"
    )
    assert r.source == "urbandictionary.com"
    assert r.provider == "urbandictionary"
    assert r.rank == 1
    assert r.published_date == "2022-03-31"
    assert r.snippet == (
        "Another word for spitting game/how good you are with pulling and "
        "sustaining bitches. | e.g. Person 1: are you from Tennessee cuz u the "
        "only ten i see"
    )
    assert r.extra["word"] == "Rizz"
    assert r.extra["defid"] == 17115763
    assert r.extra["author"] == "bro got no rizz"
    assert r.extra["thumbs_up"] == 345
    assert r.extra["thumbs_down"] == 12
    assert r.extra["written_on"] == "2022-03-31T10:36:17.000Z"
    assert r.extra["definition"] == (
        "Another word for spitting game/how good you are with pulling and "
        "sustaining bitches."
    )
    assert r.extra["example"] == (
        "Person 1: are you from Tennessee cuz u the only ten i see"
    )
    assert r.extra["total_results"] == 1


def test_urbandictionary_parse_missing_permalink_falls_back_to_term_page() -> None:
    p = UrbanDictionaryProvider()
    r = p._parse(_envelope([_LEGACY])).results[0]

    assert r.url == "https://www.urbandictionary.com/define.php?term=Test+Term"
    assert r.snippet == "A legacy entry"
    assert r.published_date is None
    assert r.extra["defid"] is None
    assert r.extra["written_on"] is None
    assert r.extra["author"] is None


def test_urbandictionary_parse_empty_fields_yield_empty_snippet() -> None:
    p = UrbanDictionaryProvider()
    item = {"word": "Empty", "definition": "   ", "example": None}
    r = p._parse(_envelope([item])).results[0]

    assert r.snippet == ""
    assert r.extra["definition"] is None
    assert r.extra["example"] is None


def test_urbandictionary_parse_collapses_whitespace_and_ignores_odd_types() -> None:
    p = UrbanDictionaryProvider()
    item = {
        "word": "  Weird   Word \n",
        "definition": "Line one\r\n\r\nLine   two",
        "example": 7,
        "defid": "17115763",
        "thumbs_up": True,
        "thumbs_down": -2,
        "permalink": "",
    }
    r = p._parse(_envelope([item])).results[0]

    assert r.title == "Weird Word"
    assert r.url == "https://www.urbandictionary.com/define.php?term=Weird+Word"
    assert r.snippet == "Line one Line two"
    assert r.extra["defid"] is None
    assert r.extra["thumbs_up"] is None
    assert r.extra["thumbs_down"] == -2
    assert r.extra["example"] is None


def test_urbandictionary_parse_deduplicates_defids() -> None:
    p = UrbanDictionaryProvider()
    duplicate = dict(_RIZZ, definition="Second copy")
    results = p._parse(_envelope([_RIZZ, duplicate, _BARE])).results

    assert [r.title for r in results] == ["Rizz", "Bare"]
    assert results[0].extra["definition"] == (
        "Another word for spitting game/how good you are with pulling and "
        "sustaining bitches."
    )
    assert [r.rank for r in results] == [1, 2]


def test_urbandictionary_parse_skips_records_without_word() -> None:
    p = UrbanDictionaryProvider()
    payload = _envelope([{}, {"definition": "no headword"}, "nope", None, _BARE])
    results = p._parse(payload).results

    assert [r.title for r in results] == ["Bare"]
    assert results[0].rank == 1


def test_urbandictionary_parse_respects_limit() -> None:
    p = UrbanDictionaryProvider()
    entries = [dict(_BARE, word=f"word{n}", defid=n) for n in range(3)]

    assert len(p._parse(_envelope(entries), limit=2).results) == 2
    assert len(p._parse(_envelope(entries)).results) == 3


def test_urbandictionary_snippet_truncates_long_fields() -> None:
    p = UrbanDictionaryProvider()
    item = {
        "word": "long",
        "definition": "definition " * 50,
        "example": "example " * 50,
    }
    r = p._parse(_envelope([item])).results[0]

    assert r.snippet.endswith("…")
    assert len(r.snippet) <= 400
    assert r.snippet.count(" | ") == 1


def test_urbandictionary_parse_empty_and_malformed() -> None:
    p = UrbanDictionaryProvider()
    assert p._parse(_envelope([])).results == []
    assert p._parse({}).results == []
    assert p._parse({"list": "nope"}).results == []
    assert p._parse({"list": [1, 2, 3]}).results == []
    assert p._parse([1, 2, 3]).results == []
    assert p._parse(None).results == []


def test_urbandictionary_helpers() -> None:
    from metasearchmcp.providers.urbandictionary import (
        _clean,
        _definition_text,
        _int,
        _terms,
        _truncate,
    )

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _clean(5) == ""

    assert _definition_text("[a] and [b]") == "a and b"
    assert _definition_text("plain\r\ntext") == "plain text"
    assert _definition_text(None) == ""

    assert _int(3) == 3
    assert _int(True) is None
    assert _int("3") is None
    assert _int(None) is None

    assert _truncate("short", 10) == "short"
    assert _truncate("a" * 10, 5) == "aaaa…"

    assert _terms(["a", "a", " b ", 5, ""]) == ["a", "b"]
    assert _terms({"terms": ["x", "x"]}) == ["x"]
    assert _terms("nope") == []
    assert _terms(None) == []


async def test_urbandictionary_search_sends_expected_request(respx_mock) -> None:
    define = respx_mock.get(_DEFINE).mock(
        return_value=respx.MockResponse(200, json=_envelope([_RIZZ, _BARE]))
    )
    autocomplete = respx_mock.get(_AUTOCOMPLETE).mock(
        return_value=respx.MockResponse(200, json=["Rizz", "rizz", "Rizzler"])
    )

    result = await UrbanDictionaryProvider().search(
        "  rizz ", SearchParams(num_results=5)
    )

    assert define.called
    assert autocomplete.called
    assert define.calls[0].request.url.params["term"] == "rizz"
    assert autocomplete.calls[0].request.url.params["term"] == "rizz"
    assert [r.title for r in result.results] == ["Rizz", "Bare"]
    assert result.suggestions == ["Rizz", "rizz", "Rizzler"]


async def test_urbandictionary_search_caps_results(respx_mock) -> None:
    entries = [dict(_BARE, word=f"word{n}", defid=n) for n in range(6)]
    respx_mock.get(_DEFINE).mock(
        return_value=respx.MockResponse(200, json=_envelope(entries))
    )
    respx_mock.get(_AUTOCOMPLETE).mock(return_value=respx.MockResponse(200, json=[]))

    provider = UrbanDictionaryProvider()
    provider._max_results = 2
    result = await provider.search("word", SearchParams(num_results=50))

    assert len(result.results) == 2
    assert result.suggestions == []


async def test_urbandictionary_search_ignores_failing_autocomplete(respx_mock) -> None:
    respx_mock.get(_DEFINE).mock(
        return_value=respx.MockResponse(200, json=_envelope([_RIZZ]))
    )
    respx_mock.get(_AUTOCOMPLETE).mock(return_value=respx.MockResponse(500))

    result = await UrbanDictionaryProvider().search("rizz", SearchParams())

    assert [r.title for r in result.results] == ["Rizz"]
    assert result.suggestions == []


async def test_urbandictionary_search_blank_query_skips_request(respx_mock) -> None:
    define = respx_mock.get(_DEFINE)
    autocomplete = respx_mock.get(_AUTOCOMPLETE)

    result = await UrbanDictionaryProvider().search("   ", SearchParams())

    assert result.results == []
    assert result.suggestions == []
    assert not define.called
    assert not autocomplete.called


async def test_urbandictionary_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_DEFINE).mock(return_value=respx.MockResponse(503))

    with pytest.raises(httpx.HTTPStatusError):
        await UrbanDictionaryProvider().search("rizz", SearchParams())
