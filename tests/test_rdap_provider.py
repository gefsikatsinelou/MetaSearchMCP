"""Unit tests for the RDAP domain registration lookup provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.rdap import (
    RdapProvider,
    _dnssec_signed,
    _entity_name,
    _event_map,
    _nameserver_list,
    _status_list,
    _str,
    _vcard_name,
    normalize_domain,
)

_REGISTRAR_ENTITY: dict[str, object] = {
    "objectClassName": "entity",
    "handle": "376",
    "roles": ["registrar"],
    "vcardArray": [
        "vcard",
        [
            ["version", {}, "text", "4.0"],
            ["fn", {}, "text", "RESERVED-Internet Assigned Numbers Authority"],
        ],
    ],
}

_SAMPLE_RESPONSE: dict[str, object] = {
    "objectClassName": "domain",
    "handle": "2336799_DOMAIN_COM-VRSN",
    "ldhName": "EXAMPLE.COM",
    "status": [
        "client delete prohibited",
        "client transfer prohibited",
        "client transfer prohibited",
    ],
    "entities": [_REGISTRAR_ENTITY],
    "events": [
        {"eventAction": "registration", "eventDate": "1995-08-14T04:00:00Z"},
        {"eventAction": "expiration", "eventDate": "2027-08-13T04:00:00Z"},
        {"eventAction": "last changed", "eventDate": "2026-08-14T08:01:43Z"},
    ],
    "secureDNS": {"delegationSigned": True},
    "nameservers": [
        {"objectClassName": "nameserver", "ldhName": "ELLIOTT.NS.CLOUDFLARE.COM"},
        {"objectClassName": "nameserver", "ldhName": "HERA.NS.CLOUDFLARE.COM"},
    ],
}

_BARE_RESPONSE: dict[str, object] = {
    "objectClassName": "domain",
    "ldhName": "203.0.113.9.in-addr.arpa",
    "status": [],
    "entities": [],
    "events": [],
    "nameservers": [],
}


def _provider() -> RdapProvider:
    return RdapProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "rdap"
    assert p.tags == ["security", "network", "web"]
    assert p.is_available() is True


def test_normalize_domain_accepts_common_query_shapes() -> None:
    assert normalize_domain("example.com") == "example.com"
    assert normalize_domain("  Example.COM  ") == "example.com"
    assert normalize_domain("www.example.com") == "example.com"
    assert normalize_domain("https://www.example.com/path?q=1") == "example.com"
    assert normalize_domain("http://example.com:443/") == "example.com"
    assert normalize_domain("https://user:pw@sub.example.co.uk/x") == (
        "sub.example.co.uk"
    )
    assert normalize_domain("example.com.") == "example.com"
    # Punycode TLDs are valid domain names.
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


def test_str_and_list_coercion() -> None:
    assert _str("  a   b ") == "a b"
    assert _str("   ") is None
    assert _str(7) is None
    assert _status_list([" client delete prohibited ", "client delete prohibited"]) == [
        "client delete prohibited"
    ]
    assert _status_list("nope") == []


def test_nameserver_list_lowercases_and_deduplicates() -> None:
    assert _nameserver_list(_SAMPLE_RESPONSE["nameservers"]) == [
        "elliott.ns.cloudflare.com",
        "hera.ns.cloudflare.com",
    ]
    assert _nameserver_list({"ldhName": "x"}) == []


def test_event_map_normalizes_actions() -> None:
    events = _event_map(_SAMPLE_RESPONSE["events"])
    assert events["registration"] == "1995-08-14T04:00:00Z"
    assert events["last_changed"] == "2026-08-14T08:01:43Z"
    assert _event_map(None) == {}
    assert _event_map([{"eventAction": "registration"}]) == {}


def test_vcard_and_entity_helpers() -> None:
    entities = _SAMPLE_RESPONSE["entities"]
    assert _vcard_name(_REGISTRAR_ENTITY["vcardArray"]) == (
        "RESERVED-Internet Assigned Numbers Authority"
    )
    assert _vcard_name("junk") is None
    assert _entity_name(entities, "registrar") == (
        "RESERVED-Internet Assigned Numbers Authority"
    )
    assert _entity_name(entities, "abuse") is None
    assert _entity_name(None, "registrar") is None


def test_dnssec_flag() -> None:
    assert _dnssec_signed({"delegationSigned": True}) is True
    assert _dnssec_signed({"delegationSigned": False}) is False
    assert _dnssec_signed({}) is None
    assert _dnssec_signed("nope") is None


def test_parse_builds_domain_result() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, "example.com")

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "RDAP: EXAMPLE.COM"
    assert r.url == "https://rdap.org/domain/example.com"
    assert r.provider == "rdap"
    assert r.source == "rdap.org"
    assert r.rank == 1
    assert "Registrar: RESERVED-Internet Assigned Numbers Authority" in r.snippet
    assert "client transfer prohibited" in r.snippet
    assert "Registered: 1995-08-14" in r.snippet
    assert "Expires: 2027-08-13" in r.snippet
    assert "Last changed: 2026-08-14" in r.snippet
    assert "elliott.ns.cloudflare.com" in r.snippet
    assert "DNSSEC: signed" in r.snippet
    assert r.extra["domain"] == "example.com"
    assert r.extra["registrar"] == "RESERVED-Internet Assigned Numbers Authority"
    assert r.extra["statuses"] == [
        "client delete prohibited",
        "client transfer prohibited",
    ]
    assert r.extra["status_count"] == 2
    assert r.extra["registered"] == "1995-08-14T04:00:00Z"
    assert r.extra["expires"] == "2027-08-13T04:00:00Z"
    assert r.extra["dnssec_signed"] is True
    assert r.extra["has_registration_date"] is True


def test_parse_missing_fields_still_returns_result() -> None:
    result = _provider()._parse(_BARE_RESPONSE, "1.0.0.127.in-addr.arpa")

    assert len(result.results) == 1
    r = result.results[0]
    assert r.extra["registrar"] is None
    assert r.extra["statuses"] == []
    assert r.extra["nameservers"] == []
    assert r.extra["dnssec_signed"] is None
    assert r.extra["has_registration_date"] is False
    assert "No registrar, status, dates or nameservers recorded." in r.snippet


def test_parse_malformed_payload() -> None:
    p = _provider()
    assert p._parse("junk", "example.com").results == []
    assert p._parse(None, "example.com").results == []


@pytest.mark.asyncio
async def test_search_hits_api_for_domain(respx_mock) -> None:
    import respx

    respx_mock.get("https://rdap.org/domain/example.com").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    result = await _provider().search(
        "https://www.example.com/path", SearchParams(num_results=5)
    )

    assert len(result.results) == 1
    assert result.results[0].provider == "rdap"
    assert len(respx_mock.calls) == 1
    assert respx_mock.calls[0].request.url.path == "/domain/example.com"


@pytest.mark.asyncio
async def test_search_skips_request_for_non_domain_query(respx_mock) -> None:
    import respx

    respx_mock.get("https://rdap.org/domain/example.com").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    empty = await _provider().search("", SearchParams(num_results=5))
    phrase = await _provider().search("openai funding", SearchParams(num_results=5))
    ip = await _provider().search("8.8.8.8", SearchParams(num_results=5))

    assert empty.results == []
    assert phrase.results == []
    assert ip.results == []
    assert len(respx_mock.calls) == 0


@pytest.mark.asyncio
async def test_search_unregistered_domain_returns_empty(respx_mock) -> None:
    import respx

    respx_mock.get("https://rdap.org/domain/unregistered.example").mock(
        return_value=respx.MockResponse(
            404,
            json={"errorCode": 404, "title": "Not Found"},
        ),
    )

    result = await _provider().search(
        "unregistered.example", SearchParams(num_results=5)
    )

    assert result.results == []
    assert len(respx_mock.calls) == 1


def test_registry_includes_rdap() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "rdap" in registry
    assert registry["rdap"].tags == ["security", "network", "web"]
