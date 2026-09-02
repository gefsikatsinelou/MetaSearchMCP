"""Unit tests for the Datamuse word-association search provider."""

from __future__ import annotations

from metasearchmcp.providers.datamuse import DatamuseProvider

_SAMPLE_RESPONSE: list[dict[str, object]] = [
    {
        "word": "sea",
        "score": 40041792,
        "tags": ["syn", "n", "results_type:primary_rel"],
    },
    {
        "word": "expanse",
        "score": 30041645,
        "tags": ["n"],
    },
    {
        # Missing word -> skipped.
        "score": 123,
    },
]


def _provider() -> DatamuseProvider:
    return DatamuseProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "datamuse"
    assert p.tags == ["web", "reference", "language"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "sea"
    assert r.url == "https://www.datamuse.com/words?ml=sea"
    assert "syn" in r.snippet
    assert "n" in r.snippet
    assert r.provider == "datamuse"
    assert r.source == "datamuse.com"
    assert r.rank == 1
    assert r.extra["score"] == 40041792
    assert r.extra["tags"] == ["syn", "n", "results_type:primary_rel"]


def test_parse_empty() -> None:
    result = _provider()._parse([])
    assert result.results == []


def test_parse_not_a_list() -> None:
    result = _provider()._parse({"error": "boom"})
    assert result.results == []


def test_parse_skips_missing_word() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert all(r.title for r in result.results)


def test_parse_no_tags_or_score() -> None:
    result = _provider()._parse([{"word": "bare"}])
    r = result.results[0]
    assert r.snippet == ""
    assert r.extra == {}


def test_parse_respects_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1
    assert result.results[0].title == "sea"
