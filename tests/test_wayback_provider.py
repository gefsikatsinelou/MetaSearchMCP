"""Unit tests for the Wayback Machine capture-history provider."""

from __future__ import annotations

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.wayback import (
    _SPARKLINE_URL,
    WaybackProvider,
    _capture_stamp,
    _count,
    _iso_date,
    _year_counts,
    extract_year,
    normalize_target,
)

_SPARKLINE_PAYLOAD = {
    "years": {
        "2002": [1, 0, 1, 0, 3, 2, 1, 25, 14, 0, 4, 0],
        "2015": [1, 2, 4, 2, 4, 2, 2, 0, 6, 3, 2, 5],
        "2016": [0] * 12,
    },
    "first_ts": "20020120142510",
    "last_ts": "20151231120000",
    "status": {"2002": "242422222424"},
}

# 2002 has 51 captures, 2015 has 33, the empty 2016 year contributes nothing.
_TOTAL_CAPTURES = 84


def _provider() -> WaybackProvider:
    return WaybackProvider()


def _route(respx_mock, target: str, payload: object) -> None:
    """Route the capture-profile lookup for *target* to *payload*."""
    respx_mock.get(
        _SPARKLINE_URL,
        params={"output": "json", "url": target, "collection": "web"},
    ).mock(return_value=respx.MockResponse(200, json=payload))


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "wayback"
    assert p.tags == ["web", "archive", "history", "knowledge"]
    assert p.is_available() is True


def test_normalize_target_accepts_common_query_shapes() -> None:
    assert normalize_target("example.com") == "example.com"
    assert normalize_target("  Example.COM  ") == "example.com"
    assert normalize_target("example.com/") == "example.com"
    assert normalize_target("https://example.com/login?next=1") == (
        "example.com/login?next=1"
    )
    assert normalize_target("http://example.com:8080/a/b") == "example.com/a/b"
    assert normalize_target("https://user:pw@sub.example.co.uk/x#frag") == (
        "sub.example.co.uk/x"
    )
    assert normalize_target("example.com.") == "example.com"
    assert normalize_target("*.example.com") == "example.com"
    assert normalize_target("example.xn--p1ai") == "example.xn--p1ai"
    # A replay URL is reduced to the address it replays.
    assert (
        normalize_target(
            "https://web.archive.org/web/20150101182316/https://example.com/login"
        )
        == "example.com/login"
    )
    assert normalize_target("web.archive.org/web/2015id_/example.com/x") == (
        "example.com/x"
    )


def test_normalize_target_rejects_non_addresses() -> None:
    assert normalize_target("") is None
    assert normalize_target("   ") is None
    assert normalize_target("example") is None
    assert normalize_target("how did this page look") is None
    assert normalize_target("8.8.8.8") is None
    assert normalize_target("2001:db8::1") is None
    assert normalize_target("-bad.com") is None
    assert normalize_target("exam ple.com") is None
    assert normalize_target("x" * 2100) is None


def test_extract_year() -> None:
    assert extract_year("example.com") == ("example.com", None)
    assert extract_year("example.com 2015") == ("example.com", 2015)
    assert extract_year("  example.com 1996  ") == ("example.com", 1996)
    # Years outside the archive's lifetime stay part of the address.
    assert extract_year("example.com 1800") == ("example.com 1800", None)
    assert extract_year("example.com 2015 extra") == ("example.com 2015 extra", None)


def test_count() -> None:
    assert _count(3) == 3
    assert _count(2.9) == 2
    assert _count(-4) == 0
    assert _count("7") == 0
    assert _count(None) == 0
    assert _count(True) == 0


def test_capture_stamp() -> None:
    assert _capture_stamp("20150101182316") == "20150101182316"
    assert _capture_stamp("2015010118231699") == "20150101182316"
    assert _capture_stamp("2015") is None
    assert _capture_stamp("not-a-stamp") is None
    assert _capture_stamp(20150101182316) is None
    assert _capture_stamp(None) is None


def test_iso_date() -> None:
    assert _iso_date("20150101182316") == "2015-01-01"
    assert _iso_date(None) is None


def test_year_counts_sorts_newest_first_and_skips_empty_years() -> None:
    counts = _year_counts(_SPARKLINE_PAYLOAD)

    assert [year for year, _ in counts] == [2015, 2002]
    assert sum(counts[1][1]) == 51
    assert sum(counts[0][1]) == 33


def test_year_counts_pads_and_truncates_months() -> None:
    counts = _year_counts({"years": {"2010": [4, 5], "2011": [0] * 15}})

    assert counts == [(2010, [4, 5] + [0] * 10)]


def test_year_counts_tolerates_junk_payloads() -> None:
    assert _year_counts("junk") == []
    assert _year_counts(None) == []
    assert _year_counts({"years": "junk"}) == []
    assert _year_counts({"years": {}}) == []
    assert _year_counts({"years": {"20": [1]}}) == []
    assert _year_counts({"years": {"year": [1]}}) == []
    assert _year_counts({"years": {"2010": "junk"}}) == []
    assert _year_counts({"years": {"2010": [0, 0, 0]}}) == []


def test_build_result_fields() -> None:
    counts = dict(_year_counts(_SPARKLINE_PAYLOAD))
    result = _provider()._build_result(
        2002, counts[2002], _SPARKLINE_PAYLOAD, "example.com", _TOTAL_CAPTURES
    )

    assert result.title == "Wayback captures of example.com in 2002"
    assert result.url == "https://web.archive.org/web/2002/example.com"
    assert result.source == "web.archive.org"
    assert result.provider == "wayback"
    assert result.snippet == (
        "51 captures in 2002 | Archived range: 2002-01-20 to 2015-12-31 | "
        "Months: Jan 1, Mar 1, May 3, Jun 2, Jul 1, Aug 25, Sep 14, Nov 4"
    )
    assert result.extra["target"] == "example.com"
    assert result.extra["year"] == 2002
    assert result.extra["captures"] == 51
    assert result.extra["total_captures"] == _TOTAL_CAPTURES
    assert result.extra["months"][7] == 25
    assert result.extra["first_capture"] == "20020120142510"
    assert result.extra["last_capture"] == "20151231120000"
    assert result.extra["first_capture_date"] == "2002-01-20"
    assert result.extra["last_capture_date"] == "2015-12-31"
    assert result.extra["replay_url"] == result.url
    assert result.extra["latest_snapshot_url"] == (
        "https://web.archive.org/web/20151231120000/example.com"
    )


def test_build_result_without_capture_stamps() -> None:
    counts = dict(_year_counts(_SPARKLINE_PAYLOAD))
    result = _provider()._build_result(
        2015, counts[2015], {"years": {"2015": counts[2015]}}, "example.com", 33
    )

    assert result.snippet == (
        "33 captures in 2015 | Months: Jan 1, Feb 2, Mar 4, Apr 2, May 4, "
        "Jun 2, Jul 2, Sep 6, Oct 3, Nov 2, Dec 5"
    )
    assert result.extra["first_capture"] is None
    assert result.extra["last_capture"] is None
    assert result.extra["latest_snapshot_url"] is None


def test_build_result_uses_singular_for_one_capture() -> None:
    result = _provider()._build_result(2010, [1] + [0] * 11, {}, "example.com", 1)

    assert result.snippet.startswith("1 capture in 2010 | Months: Jan 1")


def test_parse_ranks_years_newest_first() -> None:
    parsed = _provider()._parse(_SPARKLINE_PAYLOAD, "example.com")

    assert [r.rank for r in parsed.results] == [1, 2]
    assert [r.extra["year"] for r in parsed.results] == [2015, 2002]
    assert all(r.extra["total_captures"] == _TOTAL_CAPTURES for r in parsed.results)


def test_parse_restricts_to_a_year_and_keeps_the_total() -> None:
    parsed = _provider()._parse(_SPARKLINE_PAYLOAD, "example.com", year=2002)

    assert len(parsed.results) == 1
    assert parsed.results[0].extra["year"] == 2002
    assert parsed.results[0].extra["total_captures"] == _TOTAL_CAPTURES
    missing = _provider()._parse(_SPARKLINE_PAYLOAD, "example.com", year=1996)
    assert missing.results == []


def test_parse_respects_the_limit() -> None:
    parsed = _provider()._parse(_SPARKLINE_PAYLOAD, "example.com", limit=1)

    assert [r.extra["year"] for r in parsed.results] == [2015]


def test_parse_tolerates_junk_payloads() -> None:
    p = _provider()
    assert p._parse("junk", "example.com").results == []
    assert p._parse(None, "example.com").results == []
    unarchived = {"message": "The Wayback Machine has not archived that URL."}
    assert p._parse(unarchived, "example.com").results == []
    assert p._parse({"years": {"2016": [0] * 12}}, "example.com").results == []


@pytest.mark.asyncio
async def test_search_returns_ranked_years(respx_mock) -> None:
    _route(respx_mock, "example.com", _SPARKLINE_PAYLOAD)

    result = await _provider().search("example.com", SearchParams(num_results=5))

    assert [r.rank for r in result.results] == [1, 2]
    assert len(respx_mock.calls) == 1
    params = respx_mock.calls[0].request.url.params
    assert params["url"] == "example.com"
    assert params["output"] == "json"


@pytest.mark.asyncio
async def test_search_accepts_a_url_or_replay_query(respx_mock) -> None:
    _route(respx_mock, "example.com/login", _SPARKLINE_PAYLOAD)

    from_url = await _provider().search(
        "https://example.com/login", SearchParams(num_results=5)
    )
    from_replay = await _provider().search(
        "https://web.archive.org/web/20150101182316/https://example.com/login",
        SearchParams(num_results=5),
    )

    assert len(from_url.results) == 2
    assert len(from_replay.results) == 2
    assert len(respx_mock.calls) == 2
    assert {call.request.url.params["url"] for call in respx_mock.calls} == {
        "example.com/login"
    }


@pytest.mark.asyncio
async def test_search_restricts_to_a_trailing_year(respx_mock) -> None:
    _route(respx_mock, "example.com/index.html", _SPARKLINE_PAYLOAD)

    result = await _provider().search(
        "example.com/index.html 2015", SearchParams(num_results=5)
    )

    assert [r.extra["year"] for r in result.results] == [2015]
    assert respx_mock.calls[0].request.url.params["url"] == "example.com/index.html"


@pytest.mark.asyncio
async def test_search_respects_num_results(respx_mock) -> None:
    _route(respx_mock, "example.com", _SPARKLINE_PAYLOAD)

    result = await _provider().search("example.com", SearchParams(num_results=1))

    assert len(respx_mock.calls) == 1
    assert len(result.results) == 1


@pytest.mark.asyncio
async def test_search_skips_request_for_non_address_query(respx_mock) -> None:
    _route(respx_mock, "example.com", _SPARKLINE_PAYLOAD)

    empty = await _provider().search("", SearchParams(num_results=5))
    phrase = await _provider().search(
        "how did this page look", SearchParams(num_results=5)
    )
    year_only = await _provider().search(
        "example.com 1800", SearchParams(num_results=5)
    )

    assert empty.results == []
    assert phrase.results == []
    assert year_only.results == []
    assert len(respx_mock.calls) == 0


@pytest.mark.asyncio
async def test_search_treats_an_empty_body_as_no_captures(respx_mock) -> None:
    respx_mock.get(_SPARKLINE_URL).mock(return_value=respx.MockResponse(200, text=""))

    result = await _provider().search("example.com", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_search_treats_a_non_json_body_as_no_captures(respx_mock) -> None:
    respx_mock.get(_SPARKLINE_URL).mock(
        return_value=respx.MockResponse(200, text="<html>rate limited</html>"),
    )

    result = await _provider().search("example.com", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_SPARKLINE_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(httpx.HTTPStatusError):
        await _provider().search("example.com", SearchParams(num_results=5))


def test_registry_includes_wayback() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "wayback" in registry
    assert registry["wayback"].tags == ["web", "archive", "history", "knowledge"]
