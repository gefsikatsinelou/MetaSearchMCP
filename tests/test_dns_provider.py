"""Unit tests for the DNS-over-HTTPS record lookup provider."""

from __future__ import annotations

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.dns import (
    DnsProvider,
    _answers,
    _str,
    normalize_domain,
    parse_query,
)

_URL = "https://cloudflare-dns.com/dns-query"

_A_RESPONSE: dict[str, object] = {
    "Status": 0,
    "TC": False,
    "RD": True,
    "RA": True,
    "AD": False,
    "CD": False,
    "Question": [{"name": "example.com", "type": 1}],
    "Answer": [
        {"name": "example.com", "type": 1, "TTL": 208, "data": "104.20.23.154"},
        {"name": "example.com", "type": 1, "TTL": 260, "data": "172.66.147.243"},
        # A CNAME in the chain is not an A answer and must be ignored.
        {"name": "example.com", "type": 5, "TTL": 300, "data": "alias.example.net."},
    ],
}

_MX_RESPONSE: dict[str, object] = {
    "Status": 0,
    "AD": True,
    "Answer": [
        {
            "name": "example.com",
            "type": 15,
            "TTL": 300,
            "data": "10 mail1.example.com.",
        },
        {
            "name": "example.com",
            "type": 15,
            "TTL": 300,
            "data": "20 mail2.example.com.",
        },
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"Status": 0, "Answer": []}

_NXDOMAIN_RESPONSE: dict[str, object] = {
    "Status": 3,
    "Authority": [
        {
            "name": "com",
            "type": 6,
            "TTL": 900,
            "data": "a.gtld-servers.net. nstld.verisign-grs.com. 1790395169 1800 900",
        }
    ],
}


def _provider() -> DnsProvider:
    return DnsProvider()


def _mock(respx_mock, name: str, record_type: str, payload: dict[str, object]) -> None:
    """Route one ``name``/``type`` lookup to *payload*."""
    respx_mock.get(_URL, params={"name": name, "type": record_type}).mock(
        return_value=respx.MockResponse(200, json=payload),
    )


def _mock_all(respx_mock, response: dict[str, object]) -> None:
    """Answer every lookup with the same *response*."""
    respx_mock.get(_URL).mock(
        return_value=respx.MockResponse(200, json=response),
    )


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "dns"
    assert p.tags == ["security", "network", "dns", "web"]
    assert p.is_available() is True


def test_normalize_domain_accepts_common_query_shapes() -> None:
    assert normalize_domain("example.com") == "example.com"
    assert normalize_domain("  Example.COM  ") == "example.com"
    # Unlike RDAP the www prefix is significant for DNS lookups.
    assert normalize_domain("www.example.com") == "www.example.com"
    assert normalize_domain("https://www.example.com/path?q=1") == "www.example.com"
    assert normalize_domain("http://example.com:443/") == "example.com"
    assert normalize_domain("https://user:pw@sub.example.co.uk/x") == (
        "sub.example.co.uk"
    )
    assert normalize_domain("example.com.") == "example.com"
    assert normalize_domain("example.xn--p1ai") == "example.xn--p1ai"


def test_normalize_domain_rejects_non_domains() -> None:
    assert normalize_domain("") is None
    assert normalize_domain("   ") is None
    assert normalize_domain("example") is None
    assert normalize_domain("openai funding") is None
    assert normalize_domain("8.8.8.8") is None
    assert normalize_domain("2001:db8::1") is None
    assert normalize_domain("-bad.com") is None
    assert normalize_domain("exam ple.com") is None


def test_parse_query_defaults_to_common_record_types() -> None:
    assert parse_query("example.com") == (
        "example.com",
        ("A", "AAAA", "MX", "NS", "TXT", "CNAME"),
    )
    assert parse_query("  EXAMPLE.com  ") == (
        "example.com",
        ("A", "AAAA", "MX", "NS", "TXT", "CNAME"),
    )


def test_parse_query_accepts_record_types_on_either_side() -> None:
    assert parse_query("example.com MX") == ("example.com", ("MX",))
    assert parse_query("MX example.com") == ("example.com", ("MX",))
    assert parse_query("mx   https://example.com/x") == ("example.com", ("MX",))
    assert parse_query("example.com txt aaaa") == ("example.com", ("TXT", "AAAA"))
    assert parse_query("MX MX example.com") == ("example.com", ("MX",))
    assert parse_query("soa example.com") == ("example.com", ("SOA",))


def test_parse_query_rejects_queries_without_a_hostname() -> None:
    assert parse_query("") is None
    assert parse_query("   ") is None
    assert parse_query("MX") is None
    assert parse_query("latest news") is None
    # An unknown trailing token makes the remaining query a non-hostname.
    assert parse_query("example.com TXT please") is None


def test_str_helper() -> None:
    assert _str("  a   b ") == "a b"
    assert _str("   ") is None
    assert _str(7) is None


def test_answers_filters_by_record_type() -> None:
    assert _answers(_A_RESPONSE, 1) == [
        {"name": "example.com", "ttl": 208, "data": "104.20.23.154"},
        {"name": "example.com", "ttl": 260, "data": "172.66.147.243"},
    ]
    assert _answers(_A_RESPONSE, 15) == []
    assert _answers(_EMPTY_RESPONSE, 1) == []
    assert _answers("junk", 1) == []
    assert _answers({"Answer": [{"type": 1, "TTL": 300}]}, 1) == []


def test_build_result_fields() -> None:
    records = _answers(_A_RESPONSE, 1)
    result = _provider()._build_result("example.com", "A", records, _A_RESPONSE)

    assert result.title == "DNS A records for example.com"
    assert result.url == f"{_URL}?name=example.com&type=A"
    assert result.source == "cloudflare-dns.com"
    assert result.provider == "dns"
    assert result.snippet == "A: 104.20.23.154; 172.66.147.243 | TTL: 208s"
    assert result.extra["domain"] == "example.com"
    assert result.extra["record_type"] == "A"
    assert result.extra["record_type_code"] == 1
    assert result.extra["record_count"] == 2
    assert result.extra["records"] == ["104.20.23.154", "172.66.147.243"]
    assert result.extra["ttl"] == 208
    assert result.extra["status"] == 0
    assert result.extra["dnssec_authenticated"] is False


def test_build_result_marks_dnssec_authenticated_answers() -> None:
    records = _answers(_MX_RESPONSE, 15)
    result = _provider()._build_result("example.com", "MX", records, _MX_RESPONSE)

    assert result.extra["dnssec_authenticated"] is True
    assert result.extra["answers"][0]["data"] == "10 mail1.example.com."


@pytest.mark.asyncio
async def test_search_looks_up_every_default_record_type(respx_mock) -> None:
    _mock(respx_mock, "example.com", "A", _A_RESPONSE)
    _mock(respx_mock, "example.com", "MX", _MX_RESPONSE)
    for record_type in ("AAAA", "NS", "TXT", "CNAME"):
        _mock(respx_mock, "example.com", record_type, _EMPTY_RESPONSE)

    result = await _provider().search("example.com", SearchParams(num_results=10))

    assert [r.extra["record_type"] for r in result.results] == ["A", "MX"]
    assert [r.rank for r in result.results] == [1, 2]
    assert len(respx_mock.calls) == 6


@pytest.mark.asyncio
async def test_search_honours_explicit_record_type(respx_mock) -> None:
    _mock(respx_mock, "example.com", "MX", _MX_RESPONSE)

    result = await _provider().search("MX example.com", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].extra["record_type"] == "MX"
    assert result.results[0].extra["records"] == [
        "10 mail1.example.com.",
        "20 mail2.example.com.",
    ]
    assert len(respx_mock.calls) == 1


@pytest.mark.asyncio
async def test_search_respects_num_results(respx_mock) -> None:
    _mock(respx_mock, "example.com", "A", _A_RESPONSE)
    _mock(respx_mock, "example.com", "MX", _MX_RESPONSE)
    for record_type in ("AAAA", "NS", "TXT", "CNAME"):
        _mock(respx_mock, "example.com", record_type, _EMPTY_RESPONSE)

    result = await _provider().search("example.com", SearchParams(num_results=1))

    assert [r.extra["record_type"] for r in result.results] == ["A"]


@pytest.mark.asyncio
async def test_search_skips_request_for_non_domain_query(respx_mock) -> None:
    _mock_all(respx_mock, _A_RESPONSE)

    empty = await _provider().search("", SearchParams(num_results=5))
    phrase = await _provider().search("latest news", SearchParams(num_results=5))
    types_only = await _provider().search("MX", SearchParams(num_results=5))

    assert empty.results == []
    assert phrase.results == []
    assert types_only.results == []
    assert len(respx_mock.calls) == 0


@pytest.mark.asyncio
async def test_search_unknown_hostname_returns_empty(respx_mock) -> None:
    _mock_all(respx_mock, _NXDOMAIN_RESPONSE)

    result = await _provider().search(
        "this-domain-does-not-exist-xyz123.com", SearchParams(num_results=5)
    )

    assert result.results == []
    assert len(respx_mock.calls) == 6


@pytest.mark.asyncio
async def test_search_raises_when_every_lookup_fails(respx_mock) -> None:
    respx_mock.get(_URL).mock(side_effect=httpx.ConnectError("resolver unreachable"))

    with pytest.raises(httpx.ConnectError):
        await _provider().search("example.com MX", SearchParams(num_results=5))


@pytest.mark.asyncio
async def test_search_tolerates_a_single_failing_lookup(respx_mock) -> None:
    _mock(respx_mock, "example.com", "A", _A_RESPONSE)
    respx_mock.get(_URL, params={"name": "example.com", "type": "MX"}).mock(
        side_effect=httpx.ConnectError("resolver unreachable"),
    )

    result = await _provider().search("MX example.com A", SearchParams(num_results=5))

    assert [r.extra["record_type"] for r in result.results] == ["A"]


@pytest.mark.asyncio
async def test_search_surfaces_bare_cname_records(respx_mock) -> None:
    cname_response: dict[str, object] = {
        "Status": 0,
        "Answer": [
            {
                "name": "www.example.com",
                "type": 5,
                "TTL": 60,
                "data": "example.com.",
            }
        ],
    }
    _mock(respx_mock, "www.example.com", "CNAME", cname_response)

    result = await _provider().search(
        "www.example.com CNAME", SearchParams(num_results=5)
    )

    assert len(result.results) == 1
    assert result.results[0].extra["records"] == ["example.com."]
    assert result.results[0].extra["name"] == "www.example.com"


def test_registry_includes_dns() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "dns" in registry
    assert registry["dns"].tags == ["security", "network", "dns", "web"]
