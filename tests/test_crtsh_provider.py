"""Unit tests for the crt.sh Certificate Transparency provider."""

from __future__ import annotations

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.crtsh import (
    CrtShProvider,
    _entry_names,
    _is_expired,
    _issuer_common_name,
    _matches_domain,
    _matching_entries,
    _names,
    normalize_domain,
)

_URL = "https://crt.sh/"

_ENTRY = {
    "issuer_ca_id": 413868,
    "issuer_name": "C=US, O=SSL Corporation, CN=Cloudflare TLS Issuing ECC CA 3",
    "common_name": "example.com",
    "name_value": "*.example.com\nexample.com",
    "id": 28361964045,
    "not_before": "2026-07-29T22:10:08",
    "not_after": "2026-10-27T22:17:21",
    "serial_number": "0624D0AB311558780B7D5213B9631831",
    "result_count": 3,
}

# Same certificate, logged a second time under another log entry id.
_DUPLICATE_ENTRY = {**_ENTRY, "id": 28361996564}

# crt.sh identity search also answers names that merely contain the query.
_UNRELATED_ENTRY = {
    "issuer_ca_id": 1,
    "issuer_name": "C=US, O=Example, CN=Example CA",
    "common_name": "testexample.com",
    "name_value": "testexample.com",
    "id": 111,
    "not_before": "2024-01-01T00:00:00",
    "not_after": "2025-01-01T00:00:00",
    "serial_number": "AAAA1111",
    "result_count": 1,
}

_SUBDOMAIN_ENTRY = {
    "issuer_ca_id": 2,
    "issuer_name": "C=US, O=Let's Encrypt, CN=R3",
    "common_name": "dev.example.com",
    "name_value": "dev.example.com\napi.example.com",
    "id": 222,
    "not_before": "2020-01-01T00:00:00",
    "not_after": "2020-04-01T00:00:00",
    "serial_number": "BBBB2222",
    "result_count": 1,
}


def _provider() -> CrtShProvider:
    return CrtShProvider()


def _mock(respx_mock, domain: str, payload: object) -> None:
    """Route the crt.sh lookup for *domain* to *payload*."""
    respx_mock.get(_URL, params={"q": domain, "output": "json"}).mock(
        return_value=respx.MockResponse(200, json=payload),
    )


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "crtsh"
    assert p.tags == ["security", "network", "web", "tls"]
    assert p.is_available() is True


def test_normalize_domain_accepts_common_query_shapes() -> None:
    assert normalize_domain("example.com") == "example.com"
    assert normalize_domain("  Example.COM  ") == "example.com"
    # Certificate sets differ per name, so the www prefix is significant.
    assert normalize_domain("www.example.com") == "www.example.com"
    assert normalize_domain("https://www.example.com/path?q=1") == "www.example.com"
    assert normalize_domain("http://example.com:443/") == "example.com"
    assert normalize_domain("https://user:pw@sub.example.co.uk/x") == (
        "sub.example.co.uk"
    )
    assert normalize_domain("example.com.") == "example.com"
    assert normalize_domain("*.example.com") == "example.com"
    assert normalize_domain("%.example.com") == "example.com"
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


def test_names_splits_the_san_block() -> None:
    assert _names("*.example.com\nexample.com") == ["*.example.com", "example.com"]
    assert _names("example.com\nEXAMPLE.com\n") == ["example.com"]
    assert _names("  dev.example.com  ") == ["dev.example.com"]
    assert _names("") == []
    assert _names(None) == []


def test_entry_names_puts_the_common_name_first() -> None:
    assert _entry_names(_ENTRY) == ["example.com", "*.example.com"]
    assert _entry_names({"common_name": "a.com", "name_value": "a.com\nb.com"}) == [
        "a.com",
        "b.com",
    ]
    assert _entry_names({}) == []


def test_matches_domain_requires_equality_or_a_subdomain() -> None:
    assert _matches_domain("example.com", "example.com") is True
    assert _matches_domain("*.example.com", "example.com") is True
    assert _matches_domain("dev.example.com", "example.com") is True
    assert _matches_domain("testexample.com", "example.com") is False
    assert _matches_domain("example.com.evil.com", "example.com") is False


def test_matching_entries_filters_and_deduplicates() -> None:
    entries = _matching_entries(
        [_ENTRY, _DUPLICATE_ENTRY, _UNRELATED_ENTRY, _SUBDOMAIN_ENTRY],
        "example.com",
    )

    assert [entry["id"] for entry in entries] == [28361964045, 222]
    assert entries[0]["names"] == ["example.com", "*.example.com"]


def test_matching_entries_tolerates_junk_payloads() -> None:
    assert _matching_entries("not a list", "example.com") == []
    assert _matching_entries({"message": "rate limited"}, "example.com") == []
    assert _matching_entries([None, 7, "x"], "example.com") == []


def test_matching_entries_falls_back_when_serial_is_missing() -> None:
    first = {**_ENTRY, "serial_number": None}
    second = {**_ENTRY, "serial_number": None, "id": 999}
    entries = _matching_entries([first, second], "example.com")
    assert len(entries) == 1


def test_issuer_common_name() -> None:
    assert (
        _issuer_common_name("C=US, O=SSL Corporation, CN=Cloudflare ECC CA 3")
        == "Cloudflare ECC CA 3"
    )
    assert _issuer_common_name("CN=Let's Encrypt R3") == "Let's Encrypt R3"
    assert _issuer_common_name("C=US, O=Example") is None
    assert _issuer_common_name(None) is None


def test_is_expired_compares_iso_timestamps() -> None:
    now = "2026-09-26T00:00:00"
    assert _is_expired("2020-01-01T00:00:00", now=now) is True
    assert _is_expired("2030-01-01T00:00:00", now=now) is False
    assert _is_expired(None, now=now) is False
    assert _is_expired("", now=now) is False


def test_build_result_fields() -> None:
    entry = {**_ENTRY, "names": _entry_names(_ENTRY)}
    result = _provider()._build_result(entry, "example.com")

    assert result.title == "TLS certificate for example.com"
    assert result.url == "https://crt.sh/?id=28361964045"
    assert result.source == "crt.sh"
    assert result.provider == "crtsh"
    assert result.snippet == (
        "Issuer: Cloudflare TLS Issuing ECC CA 3 | "
        "Valid: 2026-07-29T22:10:08 to 2026-10-27T22:17:21 | "
        "Names: example.com, *.example.com"
    )
    assert result.extra["domain"] == "example.com"
    assert result.extra["common_name"] == "example.com"
    assert result.extra["certificate_id"] == 28361964045
    assert result.extra["serial_number"] == "0624D0AB311558780B7D5213B9631831"
    assert result.extra["issuer_ca_id"] == 413868
    assert result.extra["issuer_common_name"] == "Cloudflare TLS Issuing ECC CA 3"
    assert result.extra["not_before"] == "2026-07-29T22:10:08"
    assert result.extra["not_after"] == "2026-10-27T22:17:21"
    assert result.extra["names"] == ["example.com", "*.example.com"]
    assert result.extra["matched_names"] == ["example.com", "*.example.com"]
    assert result.extra["expired"] is False


def test_build_result_marks_expired_certificates_and_subdomains() -> None:
    entry = {**_SUBDOMAIN_ENTRY, "names": _entry_names(_SUBDOMAIN_ENTRY)}
    result = _provider()._build_result(entry, "example.com")

    assert result.extra["expired"] is True
    assert result.extra["matched_names"] == ["dev.example.com", "api.example.com"]
    assert "Expired" in result.snippet


def test_build_result_without_an_entry_id_falls_back_to_the_api_url() -> None:
    entry = {**_ENTRY, "id": None, "names": _entry_names(_ENTRY)}
    result = _provider()._build_result(entry, "example.com")
    assert result.url == _URL


@pytest.mark.asyncio
async def test_search_returns_deduplicated_ranked_results(respx_mock) -> None:
    _mock(
        respx_mock,
        "example.com",
        [_ENTRY, _DUPLICATE_ENTRY, _UNRELATED_ENTRY, _SUBDOMAIN_ENTRY],
    )

    result = await _provider().search("example.com", SearchParams(num_results=10))

    assert [r.rank for r in result.results] == [1, 2]
    assert [r.extra["certificate_id"] for r in result.results] == [28361964045, 222]
    assert len(respx_mock.calls) == 1
    assert respx_mock.calls[0].request.url.params["output"] == "json"


@pytest.mark.asyncio
async def test_search_accepts_a_wildcard_or_url_query(respx_mock) -> None:
    _mock(respx_mock, "example.com", [_ENTRY])

    wildcard = await _provider().search("*.example.com", SearchParams(num_results=5))
    from_url = await _provider().search(
        "https://example.com/login", SearchParams(num_results=5)
    )

    assert len(wildcard.results) == 1
    assert len(from_url.results) == 1


@pytest.mark.asyncio
async def test_search_respects_num_results(respx_mock) -> None:
    _mock(respx_mock, "example.com", [_ENTRY, _SUBDOMAIN_ENTRY])

    result = await _provider().search("example.com", SearchParams(num_results=1))

    assert len(result.results) == 1
    assert result.results[0].extra["certificate_id"] == 28361964045


@pytest.mark.asyncio
async def test_search_skips_request_for_non_domain_query(respx_mock) -> None:
    _mock(respx_mock, "example.com", [_ENTRY])

    empty = await _provider().search("", SearchParams(num_results=5))
    phrase = await _provider().search("tls certificates", SearchParams(num_results=5))

    assert empty.results == []
    assert phrase.results == []
    assert len(respx_mock.calls) == 0


@pytest.mark.asyncio
async def test_search_returns_empty_for_a_domain_without_certificates(
    respx_mock,
) -> None:
    _mock(respx_mock, "this-domain-does-not-exist-xyz123.com", [])

    result = await _provider().search(
        "this-domain-does-not-exist-xyz123.com", SearchParams(num_results=5)
    )

    assert result.results == []
    assert len(respx_mock.calls) == 1


@pytest.mark.asyncio
async def test_search_treats_a_non_list_payload_as_empty(respx_mock) -> None:
    _mock(respx_mock, "example.com", {"message": "rate limited"})

    result = await _provider().search("example.com", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(httpx.HTTPStatusError):
        await _provider().search("example.com", SearchParams(num_results=5))


def test_registry_includes_crtsh() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "crtsh" in registry
    assert registry["crtsh"].tags == ["security", "network", "web", "tls"]
