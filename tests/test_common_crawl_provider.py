"""Unit tests for the Common Crawl index provider."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.common_crawl import (
    _COLLINFO_URL,
    _INDEX_URL,
    CommonCrawlProvider,
    _byte_count,
    _human_size,
    _iso_date,
    _latest_index,
    extract_index,
    normalize_target,
    parse_query,
    parse_records,
)

_INDEX = "CC-MAIN-2026-39"

# Deliberately out of order: the newest crawl is identified by its end date,
# not by its position in the collinfo listing.
_COLLINFO = [
    {
        "id": "CC-MAIN-2026-30",
        "name": "August 2026 Index",
        "from": "2026-07-01T00:00:00",
        "to": "2026-08-01T00:00:00",
        "timegate": "https://index.commoncrawl.org/CC-MAIN-2026-30/",
        "cdx-api": "https://index.commoncrawl.org/CC-MAIN-2026-30-index",
    },
    {
        "id": "CC-MAIN-2026-39",
        "name": "September 2026 Index",
        "from": "2026-08-01T00:00:00",
        "to": "2026-09-20T00:00:00",
        "timegate": "https://index.commoncrawl.org/CC-MAIN-2026-39/",
        "cdx-api": "https://index.commoncrawl.org/CC-MAIN-2026-39-index",
    },
    {
        "id": "CC-MAIN-2024-10",
        "name": "March 2024 Index",
        "from": "2024-03-01T00:00:00",
        "to": "2024-03-20T00:00:00",
        "timegate": "https://index.commoncrawl.org/CC-MAIN-2024-10/",
        "cdx-api": "https://index.commoncrawl.org/CC-MAIN-2024-10-index",
    },
]

_WARC = "crawl-data/CC-MAIN-2026-39/segments/1788492699475.64/warc/CC-MAIN-865.warc.gz"

_NDJSON = "\n".join(
    json.dumps(record)
    for record in (
        {
            "urlkey": "com,example)/",
            "timestamp": "20260904131850",
            "url": "https://example.com/",
            "mime": "text/html",
            "status": "200",
            "digest": "DIGEST-A",
            "length": "954",
            "offset": "639725720",
            "languages": "eng",
            "filename": _WARC,
        },
        {
            "urlkey": "com,example)/",
            "timestamp": "20260905015112",
            "url": "https://example.com/",
            "mime": "text/html",
            "status": "200",
            "digest": "DIGEST-A",
            "length": "953",
            "offset": "637575428",
            "languages": "eng",
            "filename": _WARC,
        },
        {
            "urlkey": "com,example)/about",
            "timestamp": "20260904193547",
            "url": "https://example.com/about",
            "mime": "text/html",
            "status": "301",
            "digest": "DIGEST-B",
            "length": "1200",
            "offset": "185952529",
            "languages": "eng",
            "filename": _WARC,
        },
    )
)

_INDEX_ENDPOINT = _INDEX_URL.format(index=_INDEX)


def _provider() -> CommonCrawlProvider:
    return CommonCrawlProvider()


def _plan(query: str):
    """Return the query plan for *query*, which these tests expect to parse."""
    plan = parse_query(query)
    assert plan is not None
    return plan


def _record(
    url: str,
    stamp: str,
    *,
    status: str = "200",
    mime: str = "text/html",
    digest: str = "D1",
    length: str = "954",
    languages: str = "eng",
    filename: str | None = None,
) -> dict[str, object]:
    """Build an index record shaped like the ones the CDX server returns."""
    return {
        "url": url,
        "timestamp": stamp,
        "status": status,
        "mime": mime,
        "digest": digest,
        "length": length,
        "offset": "100",
        "languages": languages,
        "filename": filename or _WARC,
    }


def _route_collinfo(respx_mock, payload: object = _COLLINFO, status: int = 200) -> None:
    respx_mock.get(_COLLINFO_URL).mock(
        return_value=respx.MockResponse(status, json=payload),
    )


def _route_index(respx_mock, text: str = _NDJSON, index: str = _INDEX):
    return respx_mock.get(_INDEX_URL.format(index=index)).mock(
        return_value=respx.MockResponse(200, text=text),
    )


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "common_crawl"
    assert p.description
    assert p.tags == ["web", "archive", "data", "history"]
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


def test_extract_index() -> None:
    assert extract_index("example.com") == ("example.com", None)
    assert extract_index("example.com CC-MAIN-2024-10") == (
        "example.com",
        "CC-MAIN-2024-10",
    )
    assert extract_index("  example.com   cc-main-2024-10  ") == (
        "example.com",
        "CC-MAIN-2024-10",
    )
    # A crawl identifier on its own is not an address.
    assert extract_index("CC-MAIN-2024-10") == ("CC-MAIN-2024-10", None)
    assert extract_index("example.com 2024") == ("example.com 2024", None)


def test_parse_query_plan() -> None:
    site = parse_query("example.com")
    assert site is not None
    assert site.target == "example.com"
    assert site.match_type == "domain"
    assert site.crawl is None

    path = parse_query("https://example.com/blog")
    assert path is not None
    assert path.target == "example.com/blog"
    assert path.match_type == "prefix"

    pinned = parse_query("example.com CC-MAIN-2024-10")
    assert pinned is not None
    assert pinned.crawl == "CC-MAIN-2024-10"
    assert pinned.match_type == "domain"

    assert parse_query("how did this page look") is None
    assert parse_query("") is None


def test_latest_index_picks_the_newest_crawl() -> None:
    assert _latest_index(_COLLINFO) == _INDEX
    assert _latest_index([{"id": "CC-MAIN-2020-10"}, {"id": "CC-MAIN-2019-10"}]) == (
        "CC-MAIN-2020-10"
    )
    assert _latest_index([]) is None
    assert _latest_index("junk") is None
    assert _latest_index([{"name": "no id"}, "junk", {"id": "  "}]) is None


def test_parse_records_skips_junk_lines() -> None:
    body = "\n".join(
        (
            '{"url": "https://example.com/", "timestamp": "20260904131850"}',
            "",
            "   ",
            "<html>rate limited</html>",
            '["not", "a", "dict"]',
            '{"url": "https://example.com/about"}',
        )
    )

    assert [r["url"] for r in parse_records(body)] == [
        "https://example.com/",
        "https://example.com/about",
    ]
    assert parse_records("") == []
    assert parse_records("junk") == []


def test_byte_count_and_size_formatting() -> None:
    assert _byte_count("954") == 954
    assert _byte_count(0) == 0
    assert _byte_count(-1) is None
    assert _byte_count("not a number") is None
    assert _byte_count(None) is None
    assert _byte_count(True) is None

    assert _human_size(None) is None
    assert _human_size(954) == "954 B"
    assert _human_size(1200) == "1.2 kB"
    assert _human_size(3_400_000) == "3.4 MB"


def test_iso_date() -> None:
    assert _iso_date("20260904131850") == "2026-09-04"
    assert _iso_date("2026090") is None
    assert _iso_date("junk") is None


def test_aggregate_groups_records_by_url() -> None:
    records = [
        _record("https://example.com/", "20260101000000"),
        _record("https://example.com/", "20260904131850", digest="D2"),
        _record("https://example.com/", "20260601000000"),
        _record("https://example.com/about", "20260801000000"),
        _record("https://example.com/about", "20250501000000"),
    ]

    results = _provider()._aggregate(
        records, index=_INDEX, plan=_plan("example.com"), limit=10
    )

    assert [r.url for r in results] == [
        "https://example.com/",
        "https://example.com/about",
    ]
    assert [r.rank for r in results] == [1, 2]
    homepage = results[0]
    assert homepage.extra["captures"] == 3
    assert homepage.extra["content_versions"] == 2
    assert homepage.extra["first_capture"] == "20260101000000"
    assert homepage.extra["first_capture_date"] == "2026-01-01"
    assert homepage.extra["latest_capture"] == "20260904131850"
    assert homepage.extra["latest_capture_date"] == "2026-09-04"
    assert results[1].extra["captures"] == 2


def test_aggregate_skips_records_without_a_url() -> None:
    records = [
        _record("https://example.com/", "20260904131850"),
        {"timestamp": "20260904131850"},
        {"url": "   "},
        {"url": 42},
    ]

    results = _provider()._aggregate(
        records, index=_INDEX, plan=_plan("example.com"), limit=5
    )

    assert [r.url for r in results] == ["https://example.com/"]


def test_aggregate_ranks_the_freshest_crawl_first_and_respects_the_limit() -> None:
    records = [
        _record("https://example.com/a", "20260901000000"),
        _record("https://example.com/b", "20260903000000"),
        _record("https://example.com/c", "20260902000000"),
    ]

    results = _provider()._aggregate(
        records, index=_INDEX, plan=_plan("example.com"), limit=2
    )

    assert [r.url for r in results] == [
        "https://example.com/b",
        "https://example.com/c",
    ]


def test_build_result_fields() -> None:
    records = [
        _record("https://example.com/", "20250101000000", digest="D1"),
        _record(
            "https://example.com/",
            "20260904131850",
            status="301",
            digest="D2",
            length="1200",
        ),
    ]

    results = _provider()._aggregate(
        records, index=_INDEX, plan=_plan("example.com"), limit=5
    )

    result = results[0]
    assert result.title == "https://example.com/"
    assert result.url == "https://example.com/"
    assert result.source == "index.commoncrawl.org"
    assert result.provider == "common_crawl"
    assert result.snippet == (
        f"2 captures in {_INDEX} | Latest: 2026-09-04 (status 301) | "
        "First: 2025-01-01 | Statuses: 200, 301 | Types: text/html | "
        "Languages: eng | Content versions: 2 | Latest size: 1.2 kB"
    )
    assert result.extra["target"] == "example.com"
    assert result.extra["match_type"] == "domain"
    assert result.extra["index"] == _INDEX
    assert result.extra["statuses"] == ["200", "301"]
    assert result.extra["mime_types"] == ["text/html"]
    assert result.extra["languages"] == ["eng"]
    assert result.extra["latest_digest"] == "D2"
    assert result.extra["latest_length"] == 1200
    assert result.extra["warc_filename"] == _WARC
    assert result.extra["warc_offset"] == 100
    assert result.extra["warc_length"] == 1200
    assert result.extra["warc_url"] == f"https://data.commoncrawl.org/{_WARC}"
    assert result.extra["index_url"] == _INDEX_ENDPOINT
    assert result.extra["cdx_query_url"] == (
        f"{_INDEX_ENDPOINT}?url=example.com&output=json&matchType=domain"
    )


def test_build_result_with_a_single_capture_and_no_categories() -> None:
    results = _provider()._aggregate(
        [{"url": "https://example.com/", "timestamp": "20260904131850"}],
        index=_INDEX,
        plan=_plan("example.com"),
        limit=5,
    )

    result = results[0]
    assert result.snippet == f"1 capture in {_INDEX} | Latest: 2026-09-04"
    assert result.extra["statuses"] == []
    assert result.extra["content_versions"] == 0
    assert result.extra["first_capture_date"] == "2026-09-04"
    assert result.extra["warc_url"] is None
    assert result.extra["latest_digest"] is None


@pytest.mark.asyncio
async def test_search_resolves_the_newest_crawl_and_queries_the_domain(
    respx_mock,
) -> None:
    _route_collinfo(respx_mock)
    route = _route_index(respx_mock)

    result = await _provider().search("example.com", SearchParams(num_results=5))

    assert [r.url for r in result.results] == [
        "https://example.com/",
        "https://example.com/about",
    ]
    assert [r.rank for r in result.results] == [1, 2]
    assert result.results[0].extra["captures"] == 2
    assert result.results[0].extra["index"] == _INDEX
    assert len(respx_mock.calls) == 2
    params = route.calls[0].request.url.params
    assert params["url"] == "example.com"
    assert params["output"] == "json"
    assert params["matchType"] == "domain"
    assert params["limit"] == "50"


@pytest.mark.asyncio
async def test_search_uses_prefix_matching_for_a_path(respx_mock) -> None:
    _route_collinfo(respx_mock)
    route = _route_index(respx_mock)

    await _provider().search("https://example.com/blog", SearchParams(num_results=5))

    params = route.calls[0].request.url.params
    assert params["url"] == "example.com/blog"
    assert params["matchType"] == "prefix"


@pytest.mark.asyncio
async def test_search_pins_a_trailing_crawl_without_collinfo(respx_mock) -> None:
    _route_collinfo(respx_mock)
    route = _route_index(respx_mock, index="CC-MAIN-2024-10")

    result = await _provider().search(
        "example.com CC-MAIN-2024-10", SearchParams(num_results=5)
    )

    assert result.results[0].extra["index"] == "CC-MAIN-2024-10"
    assert len(respx_mock.calls) == 1
    assert route.calls[0].request.url.params["limit"] == "50"


@pytest.mark.asyncio
async def test_search_respects_num_results(respx_mock) -> None:
    _route_collinfo(respx_mock)
    route = _route_index(respx_mock)

    result = await _provider().search("example.com", SearchParams(num_results=1))

    assert len(result.results) == 1
    assert route.calls[0].request.url.params["limit"] == "10"


@pytest.mark.asyncio
async def test_search_treats_missing_captures_as_empty(respx_mock) -> None:
    _route_collinfo(respx_mock)
    respx_mock.get(_INDEX_ENDPOINT).mock(
        return_value=respx.MockResponse(
            404, json={"message": "No Captures found for: example.com"}
        ),
    )

    result = await _provider().search("example.com", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_search_treats_an_empty_body_as_no_captures(respx_mock) -> None:
    _route_collinfo(respx_mock)
    _route_index(respx_mock, text="")

    result = await _provider().search("example.com", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_search_treats_an_unreadable_collinfo_as_no_index(respx_mock) -> None:
    _route_collinfo(respx_mock)
    respx_mock.get(_COLLINFO_URL).mock(
        return_value=respx.MockResponse(200, text="<html>maintenance</html>"),
    )
    _route_index(respx_mock)

    result = await _provider().search("example.com", SearchParams(num_results=5))

    assert result.results == []
    assert len(respx_mock.calls) == 1


@pytest.mark.asyncio
async def test_search_skips_the_request_for_non_address_queries(respx_mock) -> None:
    _route_collinfo(respx_mock)
    _route_index(respx_mock)

    empty = await _provider().search("", SearchParams(num_results=5))
    phrase = await _provider().search(
        "how did this page look", SearchParams(num_results=5)
    )
    crawl_only = await _provider().search(
        "CC-MAIN-2024-10", SearchParams(num_results=5)
    )

    assert empty.results == []
    assert phrase.results == []
    assert crawl_only.results == []
    assert len(respx_mock.calls) == 0


@pytest.mark.asyncio
async def test_search_retries_after_a_server_error(respx_mock) -> None:
    respx_mock.get(_COLLINFO_URL).mock(
        side_effect=[
            respx.MockResponse(502, text="<html>bad gateway</html>"),
            respx.MockResponse(200, json=_COLLINFO),
        ]
    )
    _route_index(respx_mock)

    result = await _provider().search("example.com", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert len(respx_mock.calls) == 3


@pytest.mark.asyncio
async def test_search_raises_when_the_index_keeps_failing(respx_mock) -> None:
    respx_mock.get(_COLLINFO_URL).mock(
        return_value=respx.MockResponse(504, text="<html>timeout</html>"),
    )

    with pytest.raises(httpx.HTTPStatusError):
        await _provider().search("example.com", SearchParams(num_results=5))

    assert len(respx_mock.calls) == 2


def test_registry_includes_common_crawl() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "common_crawl" in registry
    assert registry["common_crawl"].tags == ["web", "archive", "data", "history"]
