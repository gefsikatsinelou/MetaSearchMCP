"""Unit tests for the Jisho Japanese-English dictionary search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.jisho import JishoProvider

_SEARCH_RESPONSE: dict[str, object] = {
    "meta": {"status": 200},
    "data": [
        {
            "slug": "改善",
            "is_common": True,
            "tags": ["wanikani19"],
            "jlpt": ["jlpt-n3"],
            "japanese": [{"word": "改善", "reading": "かいぜん"}],
            "senses": [
                {
                    "english_definitions": ["betterment", "improvement"],
                    "parts_of_speech": ["Noun", "Suru verb"],
                    "tags": [],
                    "links": [],
                    "restrictions": [],
                    "see_also": [],
                    "antonyms": [],
                    "source": [],
                    "info": [],
                },
                {
                    "english_definitions": [
                        (
                            "kaizen (Japanese business philosophy of "
                            "continuous improvement)"
                        )
                    ],
                    "parts_of_speech": ["Noun"],
                    "tags": [],
                    "links": [],
                    "restrictions": [],
                    "see_also": [],
                    "antonyms": [],
                    "source": [],
                    "info": [],
                },
            ],
            "attribution": {"jmdict": True, "jmnedict": False},
        },
        {
            "slug": "改善-2",
            "is_common": False,
            "japanese": [{"word": "改善", "reading": "かいぜん"}],
            "senses": [],
            "attribution": {"jmdict": True},
        },
        # Missing slug -> skipped.
        {"japanese": [{"word": "無題"}], "senses": []},
        # Missing headword -> skipped.
        {"slug": "orphan", "japanese": [], "senses": []},
        "junk",  # type: ignore[list-item]
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"meta": {"status": 200}, "data": []}


def _provider() -> JishoProvider:
    return JishoProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "jisho"
    assert p.tags == ["web", "reference", "language"]
    assert "no API key required" in p.description


def test_parse_basic_hit_fields() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)

    assert len(result.results) == 2
    first = result.results[0]
    assert first.title == "改善 (かいぜん)"
    assert first.url == "https://jisho.org/search/%E6%94%B9%E5%96%84"
    assert first.source == "jisho.org"
    assert first.provider == "jisho"
    assert first.rank == 1
    assert "betterment" in first.snippet
    assert "improvement" in first.snippet
    assert "Noun" in first.snippet
    assert "JLPT N3" in first.snippet
    assert "Common word" in first.snippet
    assert first.extra["slug"] == "改善"
    assert first.extra["readings"] == ["かいぜん"]
    assert first.extra["jlpt"] == ["N3"]
    assert first.extra["is_common"] is True
    assert first.extra["parts_of_speech"] == ["Noun", "Suru verb"]
    assert first.extra["sources"] == ["jmdict"]


def test_parse_entry_without_senses_or_jlpt() -> None:
    p = _provider()
    second = p._parse(_SEARCH_RESPONSE).results[1]
    assert second.title == "改善 (かいぜん)"
    assert second.extra["jlpt"] == []
    assert second.extra["is_common"] is False
    assert second.extra["parts_of_speech"] == []
    assert second.snippet == "Jisho dictionary entry"


def test_parse_skips_invalid_entries() -> None:
    p = _provider()
    # Slug-less and headword-less entries plus the junk string are skipped.
    assert len(p._parse(_SEARCH_RESPONSE).results) == 2


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({"meta": {"status": 404}, "data": []}).results == []
    assert p._parse({}).results == []
    assert p._parse(None).results == []
    assert p._parse("junk").results == []
    assert p._parse({"data": "junk"}).results == []
    assert p._parse({"data": [{}]}).results == []


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse(_SEARCH_RESPONSE, limit=1).results) == 1


def test_parse_kana_only_headword() -> None:
    p = _provider()
    payload = {
        "meta": {"status": 200},
        "data": [
            {
                "slug": "みず",
                "japanese": [{"word": "", "reading": "みず"}],
                "senses": [
                    {"english_definitions": ["water"], "parts_of_speech": ["Noun"]}
                ],
                "attribution": {"jmdict": True},
            }
        ],
    }
    result = p._parse(payload)
    assert len(result.results) == 1
    hit = result.results[0]
    assert hit.title == "みず"
    assert hit.extra["readings"] == ["みず"]


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_words_api(respx_mock) -> None:
    import respx

    respx_mock.get("https://jisho.org/api/v1/search/words").mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE)
    )

    p = _provider()
    result = await p.search("kaizen", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].title == "改善 (かいぜん)"
    call = respx_mock.calls[0]
    assert call.request.url.path == "/api/v1/search/words"
    assert call.request.url.params["keyword"] == "kaizen"
