"""Unit tests for the MyMemory translation provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.mymemory import MyMemoryProvider

_SAMPLE_RESPONSE: dict[str, object] = {
    "responseData": {
        "translatedText": "der schnelle braune Fuchs",
        "match": 0.85,
        "detectedLanguage": "en",
    },
    "quotaFinished": False,
    "responseStatus": 200,
    "matches": [
        {
            "segment": "the quick brown fox",
            "translation": "der schnelle braune Fuchs",
            "source": "en-GB",
            "target": "de-DE",
            "quality": 70,
            "usage-count": 2,
            "match": 0.85,
            "reference": "Machine Translation.",
        },
        {
            "segment": "the quick brown fox",
            "translation": "der braune Fuchs",
            "source": "en-GB",
            "target": "de-DE",
            "quality": 60,
            "usage-count": 1,
            "match": 0.6,
            "reference": "someuser",
        },
        {
            "segment": "quick brown fox",
            "translation": "brauner Fuchs",
            "source": "en-US",
            "target": "de-DE",
            "quality": 40,
            "usage-count": 5,
            "match": 0.4,
            "reference": "",
        },
        # Duplicate of "der braune Fuchs" with a higher quality -> wins.
        {
            "segment": "the quick brown fox",
            "translation": "der braune Fuchs",
            "source": "en",
            "target": "de-DE",
            "quality": 90,
            "usage-count": 3,
            "match": 0.9,
            "reference": "best",
        },
        "junk",  # not a dict -> skipped
        {"segment": "y", "translation": "", "quality": 10},  # empty -> skipped
        {"segment": "z", "translation": "MYMEMORY WARNING", "quality": 10},
    ],
}


def _provider() -> MyMemoryProvider:
    return MyMemoryProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "mymemory"
    assert p.tags == ["language", "reference", "translation"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=10, target="de")

    titles = [r.title for r in result.results]
    assert titles == [
        "der schnelle braune Fuchs",
        "der braune Fuchs",
        "brauner Fuchs",
    ]

    primary = result.results[0]
    assert primary.rank == 1
    assert primary.provider == "mymemory"
    assert primary.source == "mymemory.translated.net"
    assert primary.extra["is_machine_translation"] is True
    assert primary.extra["target_language"] == "de"
    assert primary.extra["source_language"] == "en"
    assert primary.snippet == "der schnelle braune Fuchs | machine translation"
    assert (
        primary.url
        == "https://mymemory.translated.net/en/en/de/der%20schnelle%20braune%20Fuchs"
    )


def test_parse_dedup_keeps_best_quality() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=10, target="de")
    best = result.results[1]
    assert best.title == "der braune Fuchs"
    assert best.extra["quality"] == 90
    assert best.extra["usage_count"] == 3
    assert best.extra["reference"] == "best"
    assert best.extra["segment"] == "the quick brown fox"
    assert best.snippet == (
        "the quick brown fox -> der braune Fuchs | quality 90 | used 3x"
    )
    assert best.url == "https://mymemory.translated.net/en/en/de/der%20braune%20Fuchs"


def test_parse_distinct_urls() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=10, target="de")
    urls = [r.url for r in result.results]
    assert len(urls) == len(set(urls))


def test_parse_ranks_and_skips_machine_echo() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=10, target="de")
    # Only three distinct translations remain (machine echo of primary dropped).
    assert len(result.results) == 3
    # Lower quality "brauner Fuchs" ranks after the higher-quality memory hit.
    assert result.results[2].title == "brauner Fuchs"
    assert result.results[2].extra["quality"] == 40


def test_parse_answer_box() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=10, target="de")
    assert result.answer_box is not None
    assert result.answer_box["translation"] == "der schnelle braune Fuchs"
    assert result.answer_box["source_language"] == "en"
    assert result.answer_box["target_language"] == "de"
    assert result.answer_box["alternatives"] == [
        "der schnelle braune Fuchs",
        "der braune Fuchs",
        "brauner Fuchs",
    ]


def test_parse_string_status_ok() -> None:
    payload = dict(_SAMPLE_RESPONSE)
    payload["responseStatus"] = "200"
    result = _provider()._parse(payload, limit=10, target="de")
    assert len(result.results) == 3


def test_parse_non_200_status_is_empty() -> None:
    payload = {
        "responseData": {"translatedText": "PLEASE SELECT TWO DISTINCT LANGUAGES"},
        "responseStatus": "403",
        "matches": [],
    }
    result = _provider()._parse(payload, limit=10, target="en")
    assert result.results == []
    assert result.answer_box is None


def test_parse_error_text_in_primary_only() -> None:
    payload = {
        "responseData": {
            "translatedText": "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE QUOTA",
            "match": 0,
            "detectedLanguage": "en",
        },
        "responseStatus": 200,
        "matches": [
            {
                "segment": "hello",
                "translation": "hola",
                "quality": 80,
                "usage-count": 4,
            },
        ],
    }
    result = _provider()._parse(payload, limit=10, target="es")
    # Warning text dropped, memory hit kept as the only translation.
    assert [r.title for r in result.results] == ["hola"]
    assert result.results[0].rank == 1
    assert result.results[0].extra["is_machine_translation"] is False
    assert result.answer_box is not None
    assert result.answer_box["translation"] == "hola"


def test_parse_empty_and_junk() -> None:
    p = _provider()
    assert p._parse({}, limit=10, target="de").results == []
    assert p._parse({"responseStatus": 200}, limit=10, target="de").results == []
    no_data = p._parse(
        {"responseStatus": 200, "responseData": []}, limit=10, target="de"
    )
    assert no_data.results == []
    assert p._parse([], limit=10, target="de").results == []  # type: ignore[arg-type]
    assert p._parse(None, limit=10, target="de").results == []  # type: ignore[arg-type]


def test_parse_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=2, target="de")
    assert [r.title for r in result.results] == [
        "der schnelle braune Fuchs",
        "der braune Fuchs",
    ]


def test_parse_snippet_capped_at_shared_limit() -> None:
    from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH

    long_text = "x" * (MAX_SNIPPET_LENGTH + 200)
    payload = {
        "responseData": {
            "translatedText": long_text,
            "match": 1,
            "detectedLanguage": "en",
        },
        "responseStatus": 200,
        "matches": [],
    }
    result = _provider()._parse(payload, limit=10, target="de")
    assert len(result.results[0].snippet) <= MAX_SNIPPET_LENGTH


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_langpair(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.mymemory.translated.net/get").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    params = SearchParams(num_results=5, language="de")
    result = await p.search("the quick brown fox", params)

    assert result.results[0].title == "der schnelle braune Fuchs"
    request = respx_mock.calls.last.request
    assert request.url.params["q"] == "the quick brown fox"
    assert request.url.params["langpair"] == "Autodetect|de"


@pytest.mark.asyncio
async def test_search_default_target_is_english(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.mymemory.translated.net/get").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    await p.search("hola", SearchParams(num_results=5))

    request = respx_mock.calls.last.request
    assert request.url.params["langpair"] == "Autodetect|en"


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    p = _provider()
    result = await p.search("   ", SearchParams(num_results=5))
    assert result.results == []
    assert not respx_mock.calls
