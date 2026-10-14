"""Unit tests for the keyless bible-api.com scripture search provider."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.bible import BibleProvider

_ENDPOINT = "https://bible-api.com"


def _url(reference: str) -> str:
    """Build the request URL the provider uses for a reference."""
    return f"{_ENDPOINT}/{quote(reference)}"


_ROMANS: dict[str, Any] = {
    "reference": "Romans 8:28",
    "verses": [
        {
            "book_id": "ROM",
            "book_name": "Romans",
            "chapter": 8,
            "verse": 28,
            "text": "We know that all things work together for good.\n",
        }
    ],
    "text": "We know that all things work together for good.\n",
    "translation_id": "web",
    "translation_name": "World English Bible",
}

_PSALM_23: dict[str, Any] = {
    "reference": "Psalms 23",
    "verses": [
        {
            "book_id": "PSA",
            "book_name": "Psalms",
            "chapter": 23,
            "verse": 1,
            "text": "Yahweh is my shepherd:\nI shall lack nothing.\n",
        },
        {
            "book_id": "PSA",
            "book_name": "Psalms",
            "chapter": 23,
            "verse": 2,
            "text": "He makes me lie down in green pastures.\n",
        },
    ],
    "translation_id": "web",
}


def test_bible_name_tags_and_availability() -> None:
    p = BibleProvider()
    assert p.name == "bible"
    assert p.tags == ["scripture", "religion", "reference"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_bible_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "bible" in registry
    assert registry["bible"].tags == ["scripture", "religion", "reference"]


def test_bible_parse_single_verse() -> None:
    p = BibleProvider()
    result = p._parse(_ROMANS, limit=5)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Romans 8:28"
    assert r.url == _url("Romans 8:28")
    assert r.source == "bible-api.com"
    assert r.provider == "bible"
    assert r.rank == 1
    assert r.published_date is None
    assert r.snippet == "We know that all things work together for good."
    assert r.extra["book_id"] == "ROM"
    assert r.extra["book"] == "Romans"
    assert r.extra["chapter"] == 8
    assert r.extra["verse"] == 28
    assert r.extra["translation"] == "web"


def test_bible_parse_chapter_returns_each_verse() -> None:
    p = BibleProvider()
    result = p._parse(_PSALM_23)

    assert [r.title for r in result.results] == ["Psalms 23:1", "Psalms 23:2"]
    assert [r.rank for r in result.results] == [1, 2]
    assert result.results[0].snippet == "Yahweh is my shepherd: I shall lack nothing."
    assert result.results[1].extra["verse"] == 2


def test_bible_parse_skips_unusable_verses() -> None:
    p = BibleProvider()
    payload = {
        "verses": [
            {},
            {"book_name": ""},
            {"book_name": "Mark", "chapter": 1, "verse": 1, "text": "The beginning."},
        ]
    }
    results = p._parse(payload).results
    assert [r.title for r in results] == ["Mark 1:1"]
    assert results[0].rank == 1


def test_bible_reference_falls_back_to_book_id() -> None:
    p = BibleProvider()
    payload = {"verses": [{"book_id": "JHN", "chapter": 3, "verse": 16, "text": "x"}]}
    r = p._parse(payload).results[0]

    assert r.title == "JHN 3:16"
    assert r.extra["book"] is None
    assert r.extra["book_id"] == "JHN"


def test_bible_parse_respects_limit() -> None:
    p = BibleProvider()
    assert len(p._parse(_PSALM_23, limit=1).results) == 1
    assert len(p._parse(_PSALM_23).results) == 2


def test_bible_parse_empty_and_malformed() -> None:
    p = BibleProvider()
    assert p._parse({}).results == []
    assert p._parse({"verses": []}).results == []
    assert p._parse({"error": "not found"}).results == []
    assert p._parse({"verses": "nope"}).results == []
    assert p._parse([_ROMANS]).results == []
    assert p._parse("nope").results == []
    assert p._parse(None).results == []


def test_bible_parse_ignores_odd_field_types() -> None:
    p = BibleProvider()
    payload = {
        "translation_id": 42,
        "verses": [
            {
                "book_name": "  Luke \n 1 ",
                "chapter": "1",
                "verse": True,
                "text": 7,
            }
        ],
    }
    r = p._parse(payload).results[0]

    assert r.title == "Luke 1"  # no integer chapter/verse -> book name only
    assert r.snippet == ""
    assert r.extra["chapter"] is None
    assert r.extra["verse"] is None
    assert r.extra["translation"] is None


def test_bible_helpers() -> None:
    from metasearchmcp.providers.bible import _clean, _int_or_none

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _clean(42) == ""
    assert _int_or_none(3) == 3
    assert _int_or_none(True) is None
    assert _int_or_none("3") is None
    assert _int_or_none(None) is None


async def test_bible_search_sends_expected_request(respx_mock) -> None:
    route = respx_mock.get(_url("john 3:16")).mock(
        return_value=respx.MockResponse(200, json=_ROMANS)
    )

    result = await BibleProvider().search("john 3:16", SearchParams(num_results=5))

    assert route.called
    assert route.calls[0].request.url.params["translation"] == "web"
    assert [r.title for r in result.results] == ["Romans 8:28"]


async def test_bible_search_treats_404_as_no_results(respx_mock) -> None:
    respx_mock.get(_url("artificial intelligence")).mock(
        return_value=respx.MockResponse(404, json={"error": "not found"})
    )

    result = await BibleProvider().search("artificial intelligence", SearchParams())

    assert result.results == []


async def test_bible_search_respects_result_limits(respx_mock) -> None:
    verses = [
        {"book_name": "Psalms", "chapter": 119, "verse": n, "text": f"v{n}"}
        for n in range(1, 41)
    ]
    respx_mock.get(_url("psalms 119")).mock(
        return_value=respx.MockResponse(200, json={"verses": verses})
    )

    provider = BibleProvider()
    provider._max_results = 1000
    result = await provider.search("psalms 119", SearchParams(num_results=30))
    assert len(result.results) == 30

    provider._max_results = 1
    result = await provider.search("psalms 119", SearchParams(num_results=30))
    assert len(result.results) == 1


async def test_bible_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT)

    result = await BibleProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_bible_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_url("john 3:16")).mock(return_value=respx.MockResponse(500))

    with pytest.raises(httpx.HTTPStatusError):
        await BibleProvider().search("john 3:16", SearchParams())
