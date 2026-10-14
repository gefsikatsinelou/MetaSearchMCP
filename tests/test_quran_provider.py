"""Unit tests for the keyless quran.com scripture search provider."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.quran import QuranProvider

_ENDPOINT = "https://api.quran.com/api/v4/search"


def _response(results: list[dict[str, Any]], query: str = "mercy") -> dict[str, Any]:
    """Build a quran.com search envelope around *results*."""
    return {
        "search": {
            "query": query,
            "total_results": len(results),
            "current_page": 1,
            "total_pages": 1,
            "results": results,
        }
    }


_MERCY: dict[str, Any] = _response(
    [
        {
            "verse_key": "7:151",
            "verse_id": 1105,
            "text": "قَالَ رَبِّ ٱغۡفِرۡ لِي",
            "translations": [
                {
                    "text": "He said: My Lord! Have <em>mercy</em> on me.",
                    "resource_id": 19,
                    "name": "Ahmed Ali",
                    "language_name": "english",
                }
            ],
        }
    ]
)

_PATIENCE: dict[str, Any] = _response(
    [
        {
            "verse_key": "70:5",
            "text": "فَٱصۡبِرۡ صَبۡرٗا جَمِيلًا",
            "translations": [
                {
                    "text": "So, observe <em>patience</em>, a good <em>patience</em>.",
                    "name": "T. Usmani",
                }
            ],
        },
        {
            "verse_key": "2:153",
            "text": "يَٰٓأَيُّهَا ٱلَّذِينَ آمَنُواْ",
            "translations": [
                {
                    "text": "O you who believe! Seek help through patience.",
                    "name": "Ali",
                }
            ],
        },
    ],
    query="patience",
)


def test_quran_name_tags_and_availability() -> None:
    p = QuranProvider()
    assert p.name == "quran"
    assert p.tags == ["scripture", "religion", "reference"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_quran_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "quran" in registry
    assert registry["quran"].tags == ["scripture", "religion", "reference"]


def test_quran_parse_single_verse() -> None:
    p = QuranProvider()
    result = p._parse(_MERCY, limit=5)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Qur'an 7:151"
    assert r.url == "https://quran.com/7/151"
    assert r.source == "quran.com"
    assert r.provider == "quran"
    assert r.rank == 1
    assert r.published_date is None
    assert r.snippet == "He said: My Lord! Have mercy on me."
    assert r.extra["verse_key"] == "7:151"
    assert r.extra["surah"] == 7
    assert r.extra["ayah"] == 151
    assert r.extra["arabic"] == "قَالَ رَبِّ ٱغۡفِرۡ لِي"
    assert r.extra["translation"] == "Ahmed Ali"
    assert r.extra["language"] == "english"


def test_quran_parse_preserves_order_and_ranks() -> None:
    p = QuranProvider()
    result = p._parse(_PATIENCE)

    assert [r.title for r in result.results] == ["Qur'an 70:5", "Qur'an 2:153"]
    assert [r.rank for r in result.results] == [1, 2]
    assert result.results[0].snippet == "So, observe patience, a good patience."
    assert result.results[1].extra["ayah"] == 153


def test_quran_parse_without_translation_has_empty_snippet() -> None:
    p = QuranProvider()
    payload = _response([{"verse_key": "1:1", "text": "بِسۡمِ ٱللَّهِ"}])
    r = p._parse(payload).results[0]

    assert r.title == "Qur'an 1:1"
    assert r.snippet == ""
    assert r.extra["translation"] is None
    assert r.extra["arabic"] == "بِسۡمِ ٱللَّهِ"


def test_quran_parse_skips_unusable_verses() -> None:
    p = QuranProvider()
    payload = _response(
        [
            {},
            {"verse_key": ""},
            {"verse_key": "2:255", "text": "x"},
        ]
    )
    results = p._parse(payload).results

    assert [r.title for r in results] == ["Qur'an 2:255"]
    assert results[0].rank == 1


def test_quran_verse_key_without_digits_falls_back_to_search_url() -> None:
    p = QuranProvider()
    payload = _response([{"verse_key": "0:x", "text": "x"}], query="")
    r = p._parse(payload).results[0]

    assert r.title == "Qur'an 0:x"
    assert r.url == f"{_ENDPOINT}?q="
    assert r.extra["surah"] is None
    assert r.extra["ayah"] is None


def test_quran_parse_respects_limit() -> None:
    p = QuranProvider()
    assert len(p._parse(_PATIENCE, limit=1).results) == 1
    assert len(p._parse(_PATIENCE).results) == 2


def test_quran_parse_empty_and_malformed() -> None:
    p = QuranProvider()
    assert p._parse({}).results == []
    assert p._parse({"search": {}}).results == []
    assert p._parse(_response([])).results == []
    assert p._parse({"search": {"results": "nope"}}).results == []
    assert p._parse({"search": []}).results == []
    assert p._parse([_MERCY]).results == []
    assert p._parse("nope").results == []
    assert p._parse(None).results == []


def test_quran_helpers() -> None:
    from metasearchmcp.providers.quran import (
        _clean,
        _int_or_none,
        _split_verse_key,
        _strip_markup,
    )

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _clean(42) == ""
    assert _strip_markup("Have <em>mercy</em> on me") == "Have mercy on me"
    assert _strip_markup("a &amp; b") == "a & b"
    assert _strip_markup(None) == ""
    assert _int_or_none(3) == 3
    assert _int_or_none(True) is None
    assert _int_or_none("3") is None
    assert _int_or_none(None) is None
    assert _split_verse_key("2:255") == (2, 255)
    assert _split_verse_key("0:x") == (None, None)
    assert _split_verse_key("") == (None, None)


async def test_quran_search_sends_expected_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_MERCY)
    )

    result = await QuranProvider().search("mercy", SearchParams(num_results=5))

    assert route.called
    request = route.calls[0].request
    assert request.url.params["q"] == "mercy"
    assert request.url.params["size"] == "5"
    assert request.url.params["page"] == "1"
    assert request.url.params["language"] == "en"
    assert [r.title for r in result.results] == ["Qur'an 7:151"]


async def test_quran_search_no_matches_returns_empty(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_response([], query="zzz"))
    )

    result = await QuranProvider().search("zzz", SearchParams())
    assert result.results == []


async def test_quran_search_respects_result_limits(respx_mock) -> None:
    verses = [{"verse_key": f"2:{n}", "text": f"v{n}"} for n in range(1, 41)]
    respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_response(verses, query="v"))
    )

    provider = QuranProvider()
    provider._max_results = 1000
    result = await provider.search("v", SearchParams(num_results=30))
    assert len(result.results) == 30

    provider._max_results = 1
    result = await provider.search("v", SearchParams(num_results=30))
    assert len(result.results) == 1


async def test_quran_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT)

    result = await QuranProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_quran_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(500))

    with pytest.raises(httpx.HTTPStatusError):
        await QuranProvider().search("mercy", SearchParams())
