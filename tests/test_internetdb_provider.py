"""Unit tests for the Shodan InternetDB host intelligence provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.internetdb import (
    InternetDbProvider,
    _int_list,
    _is_private,
    _str_list,
    normalize_ip,
)

_SAMPLE_RESPONSE: dict[str, object] = {
    "cpes": ["cpe:/a:cloudflare:cloudflare", "cpe:/a:openbsd:openssh:8.9"],
    "hostnames": ["one.one.one.one", "dns.example.com"],
    "ip": "1.1.1.1",
    "ports": [443, 53, 80, 8080],
    "tags": ["cdn"],
    "vulns": ["CVE-2022-0001", "CVE-2021-0002"],
}

_EMPTY_HOST: dict[str, object] = {
    "cpes": [],
    "hostnames": [],
    "ip": "203.0.113.9",
    "ports": [],
    "tags": [],
    "vulns": [],
}


def _provider() -> InternetDbProvider:
    return InternetDbProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "internetdb"
    assert p.tags == ["security", "network", "web"]
    assert p.is_available() is True


def test_normalize_ip_accepts_common_query_shapes() -> None:
    assert normalize_ip("8.8.8.8") == "8.8.8.8"
    assert normalize_ip("  8.8.8.8  ") == "8.8.8.8"
    assert normalize_ip("8.8.8.8:53") == "8.8.8.8"
    assert normalize_ip("https://8.8.8.8/status") == "8.8.8.8"
    assert normalize_ip("http://1.1.1.1:8080/path") == "1.1.1.1"
    assert normalize_ip("[2001:db8::1]") == "2001:db8::1"
    assert normalize_ip("2001:4860:4860::8888") == "2001:4860:4860::8888"
    # IPv6 literals keep their colons: only IPv4 literals get a port stripped.
    assert normalize_ip("2001:db8::1/64") == "2001:db8::1"


def test_normalize_ip_rejects_non_addresses() -> None:
    assert normalize_ip("") is None
    assert normalize_ip("   ") is None
    assert normalize_ip("example.com") is None
    assert normalize_ip("https://example.com/") is None
    assert normalize_ip("999.1.1.1") is None
    assert normalize_ip("not an ip") is None


def test_int_and_str_list_coercion() -> None:
    assert _int_list([443, "80", 443, "nope", True, None]) == [80, 443]
    assert _int_list("nope") == []
    assert _str_list([" a  b ", "a b", 7, "", None]) == ["a b"]
    assert _str_list([1, 2]) == []


def test_is_private_flag() -> None:
    assert _is_private("192.168.1.1") is True
    assert _is_private("127.0.0.1") is True
    assert _is_private("8.8.8.8") is False
    assert _is_private("not-an-ip") is False


def test_parse_builds_host_result() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, "1.1.1.1")

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Shodan InternetDB: 1.1.1.1"
    assert r.url == "https://www.shodan.io/host/1.1.1.1"
    assert r.provider == "internetdb"
    assert r.source == "shodan.io"
    assert r.rank == 1
    assert "Open ports (4): 53, 80, 443, 8080" in r.snippet
    assert "Hostnames: one.one.one.one, dns.example.com" in r.snippet
    assert "Tags: cdn" in r.snippet
    assert "cpe:/a:openbsd:openssh:8.9" in r.snippet
    assert "Known CVEs (2): CVE-2022-0001, CVE-2021-0002" in r.snippet
    assert r.extra["ip"] == "1.1.1.1"
    assert r.extra["ports"] == [53, 80, 443, 8080]
    assert r.extra["port_count"] == 4
    assert r.extra["vulns"] == ["CVE-2022-0001", "CVE-2021-0002"]
    assert r.extra["vuln_count"] == 2
    assert r.extra["has_known_vulnerabilities"] is True
    assert r.extra["is_private"] is False


def test_parse_empty_host_still_returns_result() -> None:
    result = _provider()._parse(_EMPTY_HOST, "203.0.113.9")

    assert len(result.results) == 1
    r = result.results[0]
    assert r.extra["ports"] == []
    assert r.extra["has_known_vulnerabilities"] is False
    assert "No open ports" in r.snippet


def test_parse_malformed_payload() -> None:
    p = _provider()
    assert p._parse("junk", "8.8.8.8").results == []
    assert p._parse(None, "8.8.8.8").results == []


@pytest.mark.asyncio
async def test_search_hits_api_for_ip(respx_mock) -> None:
    import respx

    respx_mock.get("https://internetdb.shodan.io/8.8.8.8").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    result = await _provider().search(" 8.8.8.8 ", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "internetdb"
    assert len(respx_mock.calls) == 1
    assert respx_mock.calls[0].request.url.path == "/8.8.8.8"


@pytest.mark.asyncio
async def test_search_skips_request_for_non_ip_query(respx_mock) -> None:
    import respx

    respx_mock.get("https://internetdb.shodan.io/example.com").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    empty = await _provider().search("", SearchParams(num_results=5))
    non_ip = await _provider().search("example.com", SearchParams(num_results=5))

    assert empty.results == []
    assert non_ip.results == []
    assert len(respx_mock.calls) == 0


@pytest.mark.asyncio
async def test_search_unknown_host_returns_empty(respx_mock) -> None:
    import respx

    respx_mock.get("https://internetdb.shodan.io/203.0.113.7").mock(
        return_value=respx.MockResponse(
            404,
            json={"detail": "No information available"},
        ),
    )

    result = await _provider().search("203.0.113.7", SearchParams(num_results=5))

    assert result.results == []
    assert len(respx_mock.calls) == 1


def test_registry_includes_internetdb() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "internetdb" in registry
    assert registry["internetdb"].tags == ["security", "network", "web"]
