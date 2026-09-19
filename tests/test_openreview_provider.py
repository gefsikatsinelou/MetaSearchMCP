"""Unit tests for the OpenReview submission provider."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.openreview import OpenReviewProvider

_ENDPOINT = "https://api2.openreview.net/notes/search"

_NOTE: dict[str, Any] = {
    "id": "MPw3obDKcD",
    "forum": "MPw3obDKcD",
    "number": 13536,
    "domain": "ICML.cc/2026/Conference",
    "license": "CC BY 4.0",
    "version": 2,
    "cdate": 1769052070527,
    "content": {
        "title": {
            "value": "AgentFold: Self-Evolving Exploration of Protein Folding Models"
        },
        "authors": {
            "value": [
                "Ada Lovelace",
                "Alan Turing",
                "Grace Hopper",
                "Katherine Johnson",
            ]
        },
        "abstract": {"value": "We introduce an agent that folds proteins."},
        "TLDR": {"value": "A self-evolving agent for protein folding."},
        "keywords": {
            "value": ["protein folding", "agents", "self-evolution", "LLM", "search"]
        },
        "venue": {"value": "Submitted to ICML 2026"},
        "venueid": {"value": "ICML.cc/2026/Conference/Submission13536"},
        "primary_area": {"value": "machine learning for sciences"},
    },
}

# A submission whose snippet must fall back to the abstract.
_BARE: dict[str, Any] = {
    "id": "WBaBx00OvZ",
    "forum": "WBaBx00OvZ",
    "cdate": 1695552920526,
    "content": {
        "title": {"value": "Sparse Submission"},
        "abstract": {"value": "Only an abstract here."},
    },
}

# Only a TLDR and a plain (non-wrapped) field value; no authors or keywords.
_ODD: dict[str, Any] = {
    "id": "iaA07eD0bP",
    "forum": "iaA07eD0bP",
    "cdate": "not-a-timestamp",
    "content": {
        "TLDR": {"value": "A summary used as the title."},
        "authors": {"value": "Solo Author"},
        "keywords": {"value": ["one", "", "  two  "]},
        "venue": "OpenReview.net/Public_Article",
    },
}


def _envelope(notes: list[Any], count: object = 8329) -> dict[str, Any]:
    """Wrap *notes* in an OpenReview search response envelope."""
    return {"notes": notes, "count": count}


def test_openreview_name_tags_and_availability() -> None:
    p = OpenReviewProvider()
    assert p.name == "openreview"
    assert p.tags == ["academic", "preprints", "ai"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_openreview_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "openreview" in registry
    assert registry["openreview"].tags == ["academic", "preprints", "ai"]


def test_openreview_parse_submission_record() -> None:
    p = OpenReviewProvider()
    result = p._parse(_envelope([_NOTE]), limit=5)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "AgentFold: Self-Evolving Exploration of Protein Folding Models"
    assert r.url == "https://openreview.net/forum?id=MPw3obDKcD"
    assert r.source == "openreview.net"
    assert r.provider == "openreview"
    assert r.rank == 1
    assert r.published_date == "2026-01-22"
    assert r.snippet == (
        "A self-evolving agent for protein folding. | "
        "Ada Lovelace, Alan Turing, Grace Hopper et al. | "
        "Submitted to ICML 2026 | "
        "protein folding, agents, self-evolution, LLM"
    )
    assert r.extra["forum"] == "MPw3obDKcD"
    assert r.extra["forum_url"] == "https://openreview.net/forum?id=MPw3obDKcD"
    assert r.extra["pdf_url"] == "https://openreview.net/pdf?id=MPw3obDKcD"
    assert r.extra["authors"] == [
        "Ada Lovelace",
        "Alan Turing",
        "Grace Hopper",
        "Katherine Johnson",
    ]
    assert r.extra["venue"] == "Submitted to ICML 2026"
    assert r.extra["venueid"] == "ICML.cc/2026/Conference/Submission13536"
    assert r.extra["primary_area"] == "machine learning for sciences"
    assert r.extra["keywords"][-1] == "search"
    assert r.extra["tldr"] == "A self-evolving agent for protein folding."
    assert r.extra["abstract"] == "We introduce an agent that folds proteins."
    assert r.extra["number"] == 13536
    assert r.extra["domain"] == "ICML.cc/2026/Conference"
    assert r.extra["license"] == "CC BY 4.0"
    assert r.extra["version"] == 2
    assert r.extra["created"] == "2026-01-22"
    assert r.extra["total_results"] == 8329


def test_openreview_parse_bare_record_falls_back_to_abstract() -> None:
    p = OpenReviewProvider()
    r = p._parse(_envelope([_BARE], count=None)).results[0]

    assert r.title == "Sparse Submission"
    assert r.url == "https://openreview.net/forum?id=WBaBx00OvZ"
    assert r.snippet == "Only an abstract here."
    assert r.published_date == "2023-09-24"
    assert r.extra["authors"] == []
    assert r.extra["keywords"] == []
    assert r.extra["venue"] is None
    assert r.extra["tldr"] is None
    assert r.extra["number"] is None
    assert r.extra["total_results"] is None


def test_openreview_parse_odd_field_types() -> None:
    p = OpenReviewProvider()
    r = p._parse(_envelope([_ODD])).results[0]

    assert r.title == "A summary used as the title."
    assert r.snippet == (
        "A summary used as the title. | Solo Author | "
        "OpenReview.net/Public_Article | one, two"
    )
    assert r.published_date is None
    assert r.extra["authors"] == ["Solo Author"]
    assert r.extra["keywords"] == ["one", "two"]
    assert r.extra["venue"] == "OpenReview.net/Public_Article"


def test_openreview_summary_is_truncated() -> None:
    p = OpenReviewProvider()
    long_abstract = "word " * 100
    note = {
        "id": "abc",
        "content": {"title": {"value": "T"}, "abstract": {"value": long_abstract}},
    }
    r = p._parse(_envelope([note])).results[0]

    assert r.snippet.endswith("…")
    assert len(r.snippet) <= 200


def test_openreview_parse_skips_records_without_title_or_id() -> None:
    p = OpenReviewProvider()
    payload = _envelope(
        [
            {},
            {"id": "no-title", "content": {"abstract": {"value": "x"}}},
            {"content": {"title": {"value": "no id"}}},
            "nope",
            _BARE,
        ]
    )
    results = p._parse(payload).results

    assert [r.title for r in results] == ["Sparse Submission"]
    assert results[0].rank == 1


def test_openreview_parse_deduplicates_forum_versions() -> None:
    p = OpenReviewProvider()
    older = dict(_NOTE, version=1, cdate=1695552920526)
    newer = dict(_NOTE, version=2)
    # A different submission sharing the query keeps its own slot.
    payload = _envelope([older, newer, _BARE])

    results = p._parse(payload).results

    assert [r.extra["forum"] for r in results] == ["MPw3obDKcD", "WBaBx00OvZ"]
    assert results[0].extra["version"] == 1
    assert [r.rank for r in results] == [1, 2]


def test_openreview_parse_respects_limit() -> None:
    p = OpenReviewProvider()
    notes = [dict(_BARE, id=f"id{n}", forum=f"id{n}") for n in range(3)]
    payload = _envelope(notes)

    assert len(p._parse(payload, limit=2).results) == 2
    assert len(p._parse(payload).results) == 3


def test_openreview_parse_empty_and_malformed() -> None:
    p = OpenReviewProvider()
    assert p._parse(_envelope([])).results == []
    assert p._parse({}).results == []
    assert p._parse({"notes": "nope"}).results == []
    assert p._parse({"notes": [1, 2, 3]}).results == []
    assert p._parse([1, 2, 3]).results == []
    assert p._parse(None).results == []
    assert p._parse({"notes": [{"id": "x", "content": "nope"}]}).results == []


def test_openreview_helpers() -> None:
    from metasearchmcp.providers.openreview import (
        _authors_line,
        _clean,
        _date,
        _field,
        _int,
        _text,
        _text_list,
        _title,
        _truncate,
    )

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _int(11) == 11
    assert _int(True) is None
    assert _int("11") is None

    assert _field({"k": {"value": 3}}, "k") == 3
    assert _field({"k": "plain"}, "k") == "plain"
    assert _field({}, "k") is None
    assert _text({"k": {"value": " a  b "}}, "k") == "a b"
    assert _text({"k": 5}, "k") == ""

    assert _text_list({"k": {"value": [" a ", "", 5]}}, "k") == ["a"]
    assert _text_list({"k": {"value": " solo "}}, "k") == ["solo"]
    assert _text_list({"k": {"value": "   "}}, "k") == []
    assert _text_list({"k": 5}, "k") == []
    assert _text_list({}, "k") == []

    assert _truncate("short", 10) == "short"
    assert _truncate("a" * 10, 5) == "aaaa…"

    assert _date(1769052070527) == "2026-01-22"
    assert _date(True) is None
    assert _date("x") is None
    assert _date(None) is None

    assert _title({"title": {"value": "T"}}) == "T"
    assert _title({"TLDR": {"value": "L"}}) == "L"
    assert _title({}) == ""

    assert _authors_line([]) == ""
    assert _authors_line(["A", "B"]) == "A, B"
    assert _authors_line(["A", "B", "C"]) == "A, B, C"
    assert _authors_line(["A", "B", "C", "D"]) == "A, B, C et al."


async def test_openreview_search_sends_expected_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope([_NOTE, _BARE]))
    )

    result = await OpenReviewProvider().search(
        "protein folding", SearchParams(num_results=5)
    )

    assert route.called
    params = route.calls[0].request.url.params
    assert params["query"] == "protein folding"
    assert params["limit"] == "5"
    assert params["offset"] == "0"
    assert params["source"] == "forum"
    assert len(respx_mock.calls) == 1
    assert [r.extra["forum"] for r in result.results] == ["MPw3obDKcD", "WBaBx00OvZ"]


async def test_openreview_search_caps_results_to_provider_limit(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(
            200,
            json=_envelope(
                [dict(_BARE, id=f"id{n}", forum=f"id{n}") for n in range(10)]
            ),
        )
    )

    provider = OpenReviewProvider()
    provider._max_results = 3
    result = await provider.search("agent", SearchParams(num_results=50))

    assert len(respx_mock.calls) == 1
    assert len(result.results) == 3
    assert respx_mock.calls[0].request.url.params["limit"] == "3"


async def test_openreview_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT)

    result = await OpenReviewProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_openreview_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(503))

    with pytest.raises(httpx.HTTPStatusError):
        await OpenReviewProvider().search("agent", SearchParams())
