"""Unit tests for the urlscan.io public scan search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.urlscan import (
    UrlscanProvider,
    _clean_text,
    _int_value,
    _str_list,
    build_search_query,
    parse_target,
)

_SAMPLE_RESPONSE: dict[str, object] = {
    "results": [
        {
            "_id": "01a0dfcb-c905-767e-8827-8a57bf493863",
            "task": {
                "visibility": "public",
                "method": "automatic",
                "source": "certstream-suspicious",
                "time": "2026-09-26T22:18:29.038Z",
                "url": "https://bad.example/",
                "tags": ["phishing"],
            },
            "page": {
                "url": "https://bad.example/",
                "domain": "bad.example",
                "apexDomain": "example",
                "ip": "203.0.113.9",
                "country": "HK",
                "server": "nginx",
                "status": "200",
                "mimeType": "text/html",
                "title": "  Fake   Portal  ",
                "asn": "AS132203",
                "asnname": "TENCENT-NET-AP-CN",
                "tlsIssuer": "YR2",
                "tlsValidFrom": "2026-09-26T21:17:26.000Z",
                "tlsAgeDays": 0,
                "tlsValidDays": 89,
                "domainAgeDays": 60,
                "apexDomainAgeDays": 817,
            },
            "stats": {
                "uniqIPs": 12,
                "uniqCountries": 4,
                "requests": 139,
                "dataLength": 12212593,
            },
            "labels": ["phishing"],
            "result": "https://urlscan.io/api/v1/result/01a0dfcb/",
            "screenshot": "https://urlscan.io/screenshots/01a0dfcb.png",
        },
        {
            "_id": "0011aabb-ccdd-eeff-0011-223344556677",
            "task": {
                "url": "http://other.example/login",
                "time": "2026-09-25T01:02:03Z",
            },
            "page": {"url": "http://other.example/login", "status": "404"},
            "stats": {},
            "labels": [],
        },
    ],
    "total": 2,
    "took": 42,
    "has_more": False,
}


def _provider() -> UrlscanProvider:
    return UrlscanProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "urlscan"
    assert p.tags == ["security", "web", "network"]
    assert p.is_available() is True
    assert "urlscan.io" in p.description


def test_parse_target_accepts_host_shapes() -> None:
    assert parse_target("example.com") == ("example.com", "")
    assert parse_target("  Example.COM  ") == ("example.com", "")
    assert parse_target("example.com/") == ("example.com", "")
    assert parse_target("example.com:8443") == ("example.com", "")
    assert parse_target("example.com:8443/login") == ("example.com", "login")
    assert parse_target("https://example.com/login?next=1") == (
        "example.com",
        "login?next=1",
    )
    # Credentials and fragments are dropped; the path is kept.
    assert parse_target("https://user:pw@example.com/a/b#frag") == (
        "example.com",
        "a/b",
    )
    assert parse_target("//example.com/x") == ("example.com", "x")
    assert parse_target("*.example.com") == ("example.com", "")
    assert parse_target("sub.example.co.uk") == ("sub.example.co.uk", "")
    assert parse_target("пример.рф") == ("xn--e1afmkfd.xn--p1ai", "")


def test_parse_target_accepts_ip_literals() -> None:
    assert parse_target("8.8.8.8") == ("8.8.8.8", "")
    assert parse_target("8.8.8.8:53") == ("8.8.8.8", "")
    assert parse_target("https://8.8.8.8/status") == ("8.8.8.8", "status")
    assert parse_target("[2001:db8::1]") == ("2001:db8::1", "")
    assert parse_target("https://[2001:db8::1]/x") == ("2001:db8::1", "x")


def test_parse_target_rejects_other_shapes() -> None:
    assert parse_target("") is None
    assert parse_target("   ") is None
    assert parse_target("example.com phishing") is None
    assert parse_target("page.domain:example.com") is None
    assert parse_target("site:example.com") is None
    assert parse_target("nginx") is None
    assert parse_target("localhost") is None
    assert parse_target("999.1.1.1") is None
    assert parse_target("example.com/a b") is None
    assert parse_target('example.com/quo"te') is None
    assert parse_target("example.com/back\\slash") is None


def test_build_search_query_rewrites_host_queries() -> None:
    assert build_search_query("example.com") == "page.domain:example.com"
    assert build_search_query(" https://example.com/path ") == (
        'page.url:"example.com/path"'
    )
    assert build_search_query("8.8.8.8") == "ip:8.8.8.8"
    assert build_search_query("https://8.8.8.8:8443/x") == 'page.url:"8.8.8.8/x"'


def test_build_search_query_passes_through_other_queries() -> None:
    assert build_search_query("page.country:RU") == "page.country:RU"
    assert build_search_query("hash:abc123") == "hash:abc123"
    assert build_search_query("phishing kit") == "phishing kit"
    assert build_search_query("nginx") == "nginx"
    assert build_search_query("local host:80") == "local host:80"


def test_build_search_query_empty_returns_none() -> None:
    assert build_search_query("") is None
    assert build_search_query("   ") is None


def test_value_coercion_helpers() -> None:
    assert _clean_text("  a \n b ") == "a b"
    assert _clean_text(None) == ""
    assert _clean_text(7) == ""
    assert _int_value(3) == 3
    assert _int_value("139") == 139
    assert _int_value(2.9) == 2
    assert _int_value(True) is None
    assert _int_value("nope") is None
    assert _int_value(None) is None
    assert _str_list(["a", " a ", "", 5, "b"]) == ["a", "b"]
    assert _str_list("nope") == []


def test_parse_builds_scan_results() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    first = result.results[0]
    assert first.title == "Fake Portal"
    assert (
        first.url == "https://urlscan.io/result/01a0dfcb-c905-767e-8827-8a57bf493863/"
    )
    assert first.source == "urlscan.io"
    assert first.provider == "urlscan"
    assert first.rank == 1
    assert first.published_date == "2026-09-26"
    assert "Scanned 2026-09-26T22:18:29.038Z" in first.snippet
    assert "Source: certstream-suspicious" in first.snippet
    assert "HTTP 200 text/html" in first.snippet
    assert "Server: nginx" in first.snippet
    assert "IP 203.0.113.9 (HK)" in first.snippet
    assert "AS132203 TENCENT-NET-AP-CN" in first.snippet
    assert "139 requests, 12 unique IPs" in first.snippet
    assert "Labels: phishing" in first.snippet
    assert first.extra["domain"] == "bad.example"
    assert first.extra["apex_domain"] == "example"
    assert first.extra["ip"] == "203.0.113.9"
    assert first.extra["asn"] == "AS132203"
    assert first.extra["status"] == "200"
    assert first.extra["requests"] == 139
    assert first.extra["unique_ips"] == 12
    assert first.extra["data_length"] == 12212593
    assert first.extra["domain_age_days"] == 60
    assert first.extra["apex_domain_age_days"] == 817
    assert first.extra["tls_issuer"] == "YR2"
    assert first.extra["labels"] == ["phishing"]
    assert first.extra["tags"] == ["phishing"]
    assert first.extra["scan_url"] == first.url
    assert first.extra["report_api_url"].endswith(
        "/01a0dfcb-c905-767e-8827-8a57bf493863/"
    )
    assert first.extra["screenshot_url"].endswith(
        "/01a0dfcb-c905-767e-8827-8a57bf493863.png"
    )

    second = result.results[1]
    assert second.title == "http://other.example/login"
    assert second.rank == 2
    assert second.extra["requests"] is None
    assert "HTTP 404" in second.snippet


def test_parse_respects_limit_and_ranks() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)

    assert len(result.results) == 1
    assert result.results[0].rank == 1


def test_parse_falls_back_to_page_url_and_skips_urlless_items() -> None:
    payload = {
        "results": [
            "junk",
            {"_id": "x", "task": {}, "page": {}},
            {
                "_id": "y",
                "page": {"url": "https://page-only.example/", "stats": "junk"},
            },
        ],
    }
    result = _provider()._parse(payload)

    assert [r.extra["task_url"] for r in result.results] == [
        "https://page-only.example/",
    ]
    # A scan without a task URL still reports the URL of the scanned page, and
    # its id addresses the report page.
    assert result.results[0].url == "https://urlscan.io/result/y/"
    assert result.results[0].published_date is None
    assert result.results[0].extra["requests"] is None


def test_parse_malformed_payloads() -> None:
    p = _provider()
    assert p._parse("junk").results == []
    assert p._parse(None).results == []
    assert p._parse({"results": "junk"}).results == []


@pytest.mark.asyncio
async def test_search_scopes_host_query(respx_mock) -> None:
    import respx

    route = respx_mock.get("https://urlscan.io/api/v1/search/").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    result = await _provider().search("example.com", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert len(respx_mock.calls) == 1
    request = route.calls[0].request
    assert request.url.params["q"] == "page.domain:example.com"
    assert request.url.params["size"] == "5"


@pytest.mark.asyncio
async def test_search_passes_through_field_query(respx_mock) -> None:
    import respx

    route = respx_mock.get("https://urlscan.io/api/v1/search/").mock(
        return_value=respx.MockResponse(200, json={"results": []}),
    )

    result = await _provider().search("page.country:RU", SearchParams(num_results=3))

    assert result.results == []
    assert route.calls[0].request.url.params["q"] == "page.country:RU"


@pytest.mark.asyncio
async def test_search_skips_request_for_empty_query(respx_mock) -> None:
    import respx

    respx_mock.get("https://urlscan.io/api/v1/search/").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    assert (await _provider().search("", SearchParams(num_results=5))).results == []
    assert (await _provider().search("   ", SearchParams(num_results=5))).results == []
    assert len(respx_mock.calls) == 0


@pytest.mark.asyncio
async def test_search_raises_on_api_error(respx_mock) -> None:
    import httpx
    import respx

    respx_mock.get("https://urlscan.io/api/v1/search/").mock(
        return_value=respx.MockResponse(
            400,
            json={"message": "Expected a field name", "status": 400},
        ),
    )

    with pytest.raises(httpx.HTTPStatusError):
        await _provider().search("page.country:RU", SearchParams(num_results=5))


def test_registry_includes_urlscan() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "urlscan" in registry
    assert registry["urlscan"].tags == ["security", "web", "network"]
