"""Unit tests for the OEIS (integer sequences) search provider."""

from __future__ import annotations

import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.oeis import OeisProvider

_SEARCH_URL = "https://oeis.org/search"

_SEARCH_RESPONSE: list[object] = [
    {
        "number": 45,
        "id": "M0692 N0256",
        "data": "0,1,1,2,3,5,8,13,21,34,55,89,144,233,377,610",
        "name": "Fibonacci numbers: F(n) = F(n-1) + F(n-2) with F(0) = 0 and F(1) = 1.",
        "comment": [
            (
                "D. E. Knuth writes: Fibonacci numbers were already discussed by\n"
                "  Indian scholars long before Fibonacci's work."
            ),
        ],
        "reference": ["Mohammad K. Azarian, The Generating Function."],
        "link": ['N. J. A. Sloane, <a href="/A000045/b000045.txt">Table</a>'],
        "formula": ["G.f.: x / (1 - x - x^2).", "F(n) = ((1+sqrt(5))^n - ...)"],
        "xref": ["Cf. A001622."],
        "keyword": "nonn,core,nice,easy,hear",
        "offset": "0,4",
        "author": "_N. J. A. Sloane_, 1964",
        "created": "1991-04-30T03:00:00-04:00",
        "time": "2026-08-27T10:07:07-04:00",
    },
    {
        "number": "290689",
        "data": "1,1,1,2,3,5,8,13,21,34,55,88,143,229",
        "name": "Number of transitive rooted trees with n nodes.",
        "author": "",
        "keyword": "nonn,nonn,",
        "created": None,
        "time": "",
    },
    {
        "id": "M0001",
        "name": "A record without a sequence number.",
        "comment": "not-a-list",
        "keyword": "",
    },
]
_EMPTY_TERMS_RECORD: dict[str, object] = {
    "number": 7,
    "name": "",
    "data": "",
    "offset": "",
    "keyword": "",
    "author": "",
    "comment": [],
}


def _provider() -> OeisProvider:
    return OeisProvider()


def test_name_tags_and_description() -> None:
    p = _provider()
    assert p.name == "oeis"
    assert p.tags == ["academic", "web", "math", "reference"]
    assert "no API key required" in p.description


def test_parse_keeps_index_order_and_rich_fields() -> None:
    result = _provider()._parse(_SEARCH_RESPONSE)

    assert [r.title.split(":")[0] for r in result.results] == ["A000045", "A290689"]
    first = result.results[0]
    assert first.title == (
        "A000045: Fibonacci numbers: F(n) = F(n-1) + F(n-2) with F(0) = 0 and F(1) = 1."
    )
    assert first.url == "https://oeis.org/A000045"
    assert first.source == "oeis.org"
    assert first.provider == "oeis"
    assert first.rank == 1
    assert first.published_date == "1991-04-30"
    assert first.snippet == (
        "Terms: 0, 1, 1, 2, 3, 5, 8, 13, 21, 34, ... | "
        "D. E. Knuth writes: Fibonacci numbers were already discussed by "
        "Indian scholars long before Fibonacci's work. | "
        "Offset: 0,4 | Keywords: nonn, core, nice, easy, hear | "
        "Author: N. J. A. Sloane, 1964"
    )
    assert first.extra == {
        "a_number": "A000045",
        "legacy_id": "M0692 N0256",
        "name": "Fibonacci numbers: F(n) = F(n-1) + F(n-2) with F(0) = 0 and F(1) = 1.",
        "terms": [
            "0",
            "1",
            "1",
            "2",
            "3",
            "5",
            "8",
            "13",
            "21",
            "34",
            "55",
            "89",
            "144",
            "233",
            "377",
            "610",
        ],
        "offset": "0,4",
        "keywords": ["nonn", "core", "nice", "easy", "hear"],
        "author": "N. J. A. Sloane, 1964",
        "comments": 1,
        "formulas": 2,
        "links": 1,
        "references": 1,
        "xrefs": 1,
        "created": "1991-04-30",
        "updated": "2026-08-27",
        "url": "https://oeis.org/A000045",
    }


def test_parse_accepts_string_number_and_dedupes_keywords() -> None:
    result = _provider()._parse(_SEARCH_RESPONSE)
    second = result.results[1]

    assert second.url == "https://oeis.org/A290689"
    assert second.rank == 2
    assert second.published_date is None
    assert second.extra["legacy_id"] is None
    assert second.extra["keywords"] == ["nonn"]
    assert second.extra["author"] is None
    assert second.snippet == (
        "Terms: 1, 1, 1, 2, 3, 5, 8, 13, 21, 34, ... | Keywords: nonn"
    )


def test_parse_skips_records_without_a_number() -> None:
    result = _provider()._parse(_SEARCH_RESPONSE)
    assert len(result.results) == 2
    assert all(r.extra["a_number"] for r in result.results)


def test_parse_handles_missing_and_malformed_fields() -> None:
    result = _provider()._parse([_EMPTY_TERMS_RECORD, *[42, "junk"]])
    only = result.results[0]

    assert only.title == "A000007"
    assert only.snippet == ""
    assert only.extra["terms"] == []
    assert only.extra["keywords"] == []
    assert only.extra["offset"] is None
    assert only.extra["comments"] == 0
    assert only.extra["created"] is None


def test_parse_elides_long_term_lists() -> None:
    long_record = {
        "number": 1,
        "data": ",".join(str(i) for i in range(20)),
        "name": "Twenty terms.",
    }
    snippet = _provider()._parse([long_record]).results[0].snippet
    assert snippet == "Terms: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, ..."


def test_parse_empty_and_malformed_payloads() -> None:
    p = _provider()
    assert p._parse(None).results == []
    assert p._parse([]).results == []
    assert p._parse({}).results == []
    assert p._parse("junk").results == []
    junk_numbers = [{"number": "junk"}, {"number": -3}, {"number": True}]
    assert p._parse(junk_numbers).results == []


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse(_SEARCH_RESPONSE, limit=1).results) == 1
    assert len(p._parse(_SEARCH_RESPONSE, 2).results) == 2


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_queries_the_json_endpoint(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE)
    )

    p = _provider()
    result = await p.search("1,2,3,5,8,13", SearchParams(num_results=5))

    assert [r.url for r in result.results] == [
        "https://oeis.org/A000045",
        "https://oeis.org/A290689",
    ]
    call = respx_mock.calls[0]
    assert call.request.url.params["q"] == "1,2,3,5,8,13"
    assert call.request.url.params["fmt"] == "json"


@pytest.mark.asyncio
async def test_search_caps_results_at_endpoint_page_size(respx_mock) -> None:
    many = [{"number": n, "name": f"Sequence {n}."} for n in range(1, 31)]
    respx_mock.get(_SEARCH_URL).mock(return_value=respx.MockResponse(200, json=many))

    p = _provider()
    result = await p.search("prime", SearchParams(num_results=50))

    assert len(result.results) == 10


@pytest.mark.asyncio
async def test_search_skips_blank_query(respx_mock) -> None:
    route = respx_mock.get(_SEARCH_URL)

    p = _provider()
    result = await p.search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_handles_null_response(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(
            200,
            content=b"null",
            headers={"content-type": "application/json"},
        )
    )

    p = _provider()
    result = await p.search("zzzznotasequencexyz", SearchParams(num_results=5))

    assert result.results == []
