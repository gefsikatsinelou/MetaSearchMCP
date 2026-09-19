"""Unit tests for the Tatoeba example-sentence provider."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.tatoeba import TatoebaProvider

_ENDPOINT = "https://tatoeba.org/en/api_v0/search"

_SENTENCE: dict[str, Any] = {
    "id": 11144401,
    "text": "Hello world!",
    "lang": "eng",
    "correctness": 0,
    "script": None,
    "license": "CC BY 2.0 FR",
    "translations": [
        [
            {
                "id": 398752,
                "text": "Hallo, Welt!",
                "lang": "deu",
                "lang_name": "German",
                "lang_tag": "de",
                "isDirect": True,
                "audios": [{"id": 1, "download_url": "/en/audio/download/1"}],
            },
            {
                "id": 428145,
                "text": "Saluton, mondo!",
                "lang": "epo",
                "lang_name": "Esperanto",
                "lang_tag": "eo",
                "isDirect": True,
            },
        ]
    ],
    "transcriptions": [
        {
            "id": 2401780,
            "sentence_id": 11144401,
            "script": "Latn",
            "text": "Hello, world!",
        }
    ],
    "audios": [
        {
            "id": 894762,
            "source": "tatoeba",
            "author": "CK",
            "download_url": "/en/audio/download/894762",
        }
    ],
    "user": {"username": "small_snow"},
    "lang_name": "English",
    "dir": "ltr",
    "lang_tag": "en",
    "max_visible_translations": 5,
}

_BARE: dict[str, Any] = {"id": 7, "text": "Sparse sentence.", "lang_name": "English"}

_WITHOUT_AUDIO: dict[str, Any] = {
    "id": 8,
    "text": "No audio here.",
    "lang": "jpn",
    "lang_name": "Japanese",
    "transcriptions": [{"text": "ここには音声がありません。"}],
    "user": {"username": None},
}


def _envelope(records: list[Any], total: object = 718) -> dict[str, Any]:
    """Wrap *records* in a Tatoeba search response envelope."""
    return {
        "paging": {
            "Sentences": {
                "count": total,
                "perPage": 10,
                "page": 1,
                "pageCount": 72,
            }
        },
        "results": records,
    }


def test_tatoeba_name_tags_and_availability() -> None:
    p = TatoebaProvider()
    assert p.name == "tatoeba"
    assert p.tags == ["web", "reference", "language"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_tatoeba_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "tatoeba" in registry
    assert registry["tatoeba"].tags == ["web", "reference", "language"]


def test_tatoeba_parse_sentence_record() -> None:
    p = TatoebaProvider()
    result = p._parse(_envelope([_SENTENCE]), limit=5)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Hello world!"
    assert r.url == "https://tatoeba.org/en/sentences/show/11144401"
    assert r.source == "tatoeba.org"
    assert r.provider == "tatoeba"
    assert r.rank == 1
    assert r.published_date is None
    assert r.snippet == (
        "English | Hello, world! | Hallo, Welt! (German) | "
        "Saluton, mondo! (Esperanto) | by small_snow | audio available"
    )
    assert r.extra["sentence_id"] == 11144401
    assert r.extra["language"] == "eng"
    assert r.extra["language_name"] == "English"
    assert r.extra["language_tag"] == "en"
    assert r.extra["script"] is None
    assert r.extra["license"] == "CC BY 2.0 FR"
    assert r.extra["owner"] == "small_snow"
    assert r.extra["transcription"] == "Hello, world!"
    assert r.extra["audio_url"] == "https://tatoeba.org/en/audio/download/894762"
    assert r.extra["sentence_url"] == "https://tatoeba.org/en/sentences/show/11144401"
    assert r.extra["translation_count"] == 2
    assert r.extra["total_results"] == 718
    assert r.extra["translations"] == [
        {
            "id": 398752,
            "language": "deu",
            "language_name": "German",
            "text": "Hallo, Welt!",
        },
        {
            "id": 428145,
            "language": "epo",
            "language_name": "Esperanto",
            "text": "Saluton, mondo!",
        },
    ]


def test_tatoeba_parse_bare_record() -> None:
    p = TatoebaProvider()
    r = p._parse(_envelope([_BARE], total=None)).results[0]

    assert r.title == "Sparse sentence."
    assert r.url == "https://tatoeba.org/en/sentences/show/7"
    assert r.snippet == "English"
    assert r.extra["translations"] == []
    assert r.extra["translation_count"] == 0
    assert r.extra["owner"] is None
    assert r.extra["audio_url"] is None
    assert r.extra["transcription"] is None
    assert r.extra["license"] is None
    assert r.extra["total_results"] is None


def test_tatoeba_snippet_uses_transcription_without_owner() -> None:
    p = TatoebaProvider()
    r = p._parse(_envelope([_WITHOUT_AUDIO])).results[0]

    assert r.snippet == "Japanese | ここには音声がありません。"
    assert r.extra["owner"] is None
    assert r.extra["audio_url"] is None


def test_tatoeba_title_is_truncated() -> None:
    p = TatoebaProvider()
    long_text = "a" * 150
    r = p._parse(_envelope([{"id": 9, "text": long_text}])).results[0]

    assert len(r.title) == 100
    assert r.title.endswith("...")
    assert r.title == "a" * 97 + "..."

    exact = "b" * 100
    r = p._parse(_envelope([{"id": 10, "text": exact}])).results[0]
    assert r.title == exact


def test_tatoeba_parse_skips_records_without_text() -> None:
    p = TatoebaProvider()
    payload = _envelope([{}, {"id": 3}, {"text": "no id"}, "nope", _BARE])
    results = p._parse(payload).results

    assert [r.extra["sentence_id"] for r in results] == [7]
    assert results[0].rank == 1


def test_tatoeba_parse_respects_limit_and_start_rank() -> None:
    p = TatoebaProvider()
    records = [dict(_BARE, id=n) for n in (1, 2, 3)]
    payload = _envelope(records)

    assert len(p._parse(payload, limit=2).results) == 2
    assert len(p._parse(payload).results) == 3
    assert p._parse(payload, limit=2, start_rank=11).results[1].rank == 12


def test_tatoeba_parse_empty_and_malformed() -> None:
    p = TatoebaProvider()
    assert p._parse(_envelope([])).results == []
    assert p._parse({}).results == []
    assert p._parse({"results": "nope"}).results == []
    assert p._parse({"results": [1, 2, 3]}).results == []
    assert p._parse({"paging": "nope", "results": []}).results == []
    assert p._parse([1, 2, 3]).results == []
    assert p._parse(None).results == []


def test_tatoeba_parse_ignores_odd_field_types() -> None:
    p = TatoebaProvider()
    payload = _envelope(
        [
            {
                "id": True,
                "text": 42,
            },
            {
                "id": 11,
                "text": "  Odd   spacing  ",
                "lang": 5,
                "lang_name": None,
                "lang_tag": None,
                "license": 7,
                "user": "nope",
                "translations": ["nope", [{"text": ""}, {"text": 5}]],
                "transcriptions": "nope",
                "audios": "nope",
            },
        ],
        total="many",
    )
    r = p._parse(payload).results[0]

    assert r.title == "Odd spacing"
    assert r.extra["language"] is None
    assert r.extra["language_name"] is None
    assert r.extra["translations"] == []
    assert r.extra["total_results"] is None


def test_tatoeba_helpers() -> None:
    from metasearchmcp.providers.tatoeba import (
        _audio_url,
        _clean,
        _int,
        _iso_code,
        _total_results,
        _transcription,
        _translations,
    )

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _int(11) == 11
    assert _int(True) is None
    assert _int("11") is None

    assert _iso_code("en") == "eng"
    assert _iso_code("EN_us") == "eng"
    assert _iso_code("zh-TW") == "cmn"
    assert _iso_code("deu") == "deu"
    assert _iso_code("") is None
    assert _iso_code(None) is None
    assert _iso_code("xx") is None
    assert _iso_code("x1") is None

    assert _total_results({"paging": {"Sentences": {"count": 12}}}) == 12
    assert _total_results({"paging": {}}) is None
    assert _total_results({}) is None

    assert _translations([[{"text": " hi ", "lang": "deu"}], {"text": ""}]) == [
        {"id": None, "language": "deu", "language_name": None, "text": "hi"}
    ]
    assert _translations("nope") == []

    assert _transcription([{"text": "reading"}]) == "reading"
    assert _transcription([{"text": ""}, {"text": "second"}]) == "second"
    assert _transcription([]) == ""
    assert _transcription("nope") == ""

    assert _audio_url([{"download_url": "/en/audio/download/1"}]) == (
        "https://tatoeba.org/en/audio/download/1"
    )
    assert _audio_url([{"download_url": "https://x/a.mp3"}]) == "https://x/a.mp3"
    assert _audio_url([{"download_url": ""}, {"download_url": "/a/2"}]) == (
        "https://tatoeba.org/a/2"
    )
    assert _audio_url([]) == ""
    assert _audio_url("nope") == ""


async def test_tatoeba_search_sends_expected_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope([_SENTENCE, _BARE]))
    )

    result = await TatoebaProvider().search("hello", SearchParams(num_results=5))

    assert route.called
    params = route.calls[0].request.url.params
    assert params["query"] == "hello"
    assert params["from"] == "eng"
    assert params["sort"] == "relevance"
    assert params["page"] == "1"
    assert len(respx_mock.calls) == 1
    assert [r.extra["sentence_id"] for r in result.results] == [11144401, 7]


async def test_tatoeba_search_maps_language_codes(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope([_BARE]))
    )

    provider = TatoebaProvider()
    await provider.search("hallo", SearchParams(language="de"))
    assert respx_mock.calls[0].request.url.params["from"] == "deu"

    await provider.search("hallo", SearchParams(language="jpn"))
    assert respx_mock.calls[1].request.url.params["from"] == "jpn"

    await provider.search("hallo", SearchParams(language="xx"))
    assert "from" not in respx_mock.calls[2].request.url.params


async def test_tatoeba_search_pages_until_limit(respx_mock) -> None:
    first_page = [dict(_BARE, id=n) for n in range(1, 11)]
    second_page = [dict(_BARE, id=n) for n in range(11, 14)]
    respx_mock.get(_ENDPOINT).mock(
        side_effect=[
            respx.MockResponse(200, json=_envelope(first_page)),
            respx.MockResponse(200, json=_envelope(second_page)),
        ]
    )

    provider = TatoebaProvider()
    provider._max_results = 25
    result = await provider.search("sentence", SearchParams(num_results=12))

    assert len(respx_mock.calls) == 2
    assert respx_mock.calls[0].request.url.params["page"] == "1"
    assert respx_mock.calls[1].request.url.params["page"] == "2"
    assert [r.extra["sentence_id"] for r in result.results] == list(range(1, 13))
    assert [r.rank for r in result.results] == list(range(1, 13))


async def test_tatoeba_search_does_not_page_past_short_page(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope([dict(_BARE, id=1)]))
    )

    result = await TatoebaProvider().search("sentence", SearchParams(num_results=50))

    assert len(respx_mock.calls) == 1
    assert len(result.results) == 1


async def test_tatoeba_search_caps_results_to_provider_limit(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(
            200,
            json=_envelope([dict(_BARE, id=n) for n in range(1, 11)]),
        )
    )

    provider = TatoebaProvider()
    provider._max_results = 3
    result = await provider.search("sentence", SearchParams(num_results=50))

    assert len(respx_mock.calls) == 1
    assert len(result.results) == 3


async def test_tatoeba_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT)

    result = await TatoebaProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_tatoeba_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(503))

    with pytest.raises(httpx.HTTPStatusError):
        await TatoebaProvider().search("hello", SearchParams())
