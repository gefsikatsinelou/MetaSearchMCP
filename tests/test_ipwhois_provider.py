"""Unit tests for the ipwho.is IP geolocation provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.ipwhois import (
    IpWhoisProvider,
    _asn,
    _number,
    _str,
)

_API_URL = "https://ipwho.is/8.8.8.8"

_SAMPLE_RESPONSE: dict[str, object] = {
    "ip": "8.8.8.8",
    "success": True,
    "type": "IPv4",
    "continent": "North America",
    "continent_code": "NA",
    "country": "United States",
    "country_code": "US",
    "region": "California",
    "region_code": "CA",
    "city": "San Jose",
    "latitude": 37.3393939,
    "longitude": -121.8949553,
    "is_eu": False,
    "postal": "95025",
    "calling_code": "1",
    "capital": "Washington D.C.",
    "borders": "CA,MX",
    "flag": {
        "img": "https://cdn.ipwhois.io/flags/us.svg",
        "emoji": "\U0001f1fa\U0001f1f8",
        "emoji_unicode": "U+1F1FA U+1F1F8",
    },
    "connection": {
        "asn": 15169,
        "org": "Google LLC",
        "isp": "Google LLC",
        "domain": "google.com",
    },
    "timezone": {
        "id": "America/Los_Angeles",
        "abbr": "PDT",
        "is_dst": True,
        "offset": -25200,
        "utc": "-07:00",
    },
}

# Reserve range: ipwho.is answers success=false with a message.
_RESERVED: dict[str, object] = {
    "ip": "192.168.1.1",
    "success": False,
    "message": "Reserved range",
}


def _provider() -> IpWhoisProvider:
    return IpWhoisProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "ipwhois"
    assert p.tags == ["network", "geo", "web"]
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "ipwhois" in registry
    assert registry["ipwhois"].tags == ["network", "geo", "web"]


def test_scalar_coercion_helpers() -> None:
    assert _str("  a  b ") == "a b"
    assert _str("") is None
    assert _str(7) is None
    assert _number(1) == 1.0
    assert _number(-121.5) == -121.5
    assert _number(True) is None
    assert _number("8") is None
    assert _asn(15169) == 15169
    assert _asn(True) is None
    assert _asn("15169") is None


def test_parse_builds_geolocation_result() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, "8.8.8.8")

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "IP geolocation: 8.8.8.8"
    assert r.url == _API_URL
    assert r.provider == "ipwhois"
    assert r.source == "ipwho.is"
    assert r.rank == 1

    assert "United States (US)" in r.snippet
    assert "San Jose, California" in r.snippet
    assert "Postal: 95025" in r.snippet
    assert "37.3393939, -121.8949553" in r.snippet
    assert "Google LLC" in r.snippet
    assert "AS15169" in r.snippet
    assert "America/Los_Angeles" in r.snippet

    assert r.extra["ip"] == "8.8.8.8"
    assert r.extra["type"] == "IPv4"
    assert r.extra["continent"] == "North America"
    assert r.extra["country"] == "United States"
    assert r.extra["country_code"] == "US"
    assert r.extra["region"] == "California"
    assert r.extra["city"] == "San Jose"
    assert r.extra["postal"] == "95025"
    assert r.extra["latitude"] == 37.3393939
    assert r.extra["longitude"] == -121.8949553
    assert r.extra["is_eu"] is False
    assert r.extra["capital"] == "Washington D.C."
    assert r.extra["calling_code"] == "1"
    assert r.extra["asn"] == 15169
    assert r.extra["organization"] == "Google LLC"
    assert r.extra["isp"] == "Google LLC"
    assert r.extra["domain"] == "google.com"
    assert r.extra["timezone"] == "America/Los_Angeles"
    assert r.extra["utc_offset"] == "-07:00"
    assert r.extra["flag"] == "\U0001f1fa\U0001f1f8"
    assert r.extra["flag_image"] == "https://cdn.ipwhois.io/flags/us.svg"


def test_snippet_shows_eu_and_distinct_isp() -> None:
    data = dict(_SAMPLE_RESPONSE)
    data["is_eu"] = True
    data["connection"] = {
        "asn": 3320,
        "org": "Deutsche Telekom AG",
        "isp": "T-Online",
    }
    result = _provider()._parse(data, "8.8.8.8")
    snippet = result.results[0].snippet
    assert "ISP: T-Online" in snippet
    assert "Deutsche Telekom AG" in snippet
    assert "EU" in snippet


def test_parse_success_false_returns_empty() -> None:
    assert _provider()._parse(_RESERVED, "192.168.1.1").results == []


def test_parse_malformed_payload() -> None:
    p = _provider()
    assert p._parse("junk", "8.8.8.8").results == []
    assert p._parse(None, "8.8.8.8").results == []
    assert p._parse({"success": "yes"}, "8.8.8.8").results == []


def test_snippet_is_truncated_to_shared_limit() -> None:
    data = dict(_SAMPLE_RESPONSE)
    data["country"] = "word " * 200
    result = _provider()._parse(data, "8.8.8.8")
    assert len(result.results[0].snippet) <= 400


@pytest.mark.asyncio
async def test_search_hits_api_for_ip(respx_mock) -> None:
    import respx

    respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    result = await _provider().search("  8.8.8.8  ", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "ipwhois"
    assert len(respx_mock.calls) == 1
    assert respx_mock.calls[0].request.url.path == "/8.8.8.8"


@pytest.mark.asyncio
async def test_search_accepts_url_query(respx_mock) -> None:
    import respx

    route = respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    result = await _provider().search(
        "https://8.8.8.8/status", SearchParams(num_results=5)
    )

    assert len(result.results) == 1
    assert route.called


@pytest.mark.asyncio
async def test_search_skips_request_for_non_ip_query(respx_mock) -> None:
    import respx

    respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    empty = await _provider().search("", SearchParams(num_results=5))
    hostname = await _provider().search("example.com", SearchParams(num_results=5))

    assert empty.results == []
    assert hostname.results == []
    assert len(respx_mock.calls) == 0


@pytest.mark.asyncio
async def test_search_reserved_range_returns_empty(respx_mock) -> None:
    import respx

    respx_mock.get("https://ipwho.is/192.168.1.1").mock(
        return_value=respx.MockResponse(200, json=_RESERVED),
    )

    result = await _provider().search("192.168.1.1", SearchParams(num_results=5))

    assert result.results == []
    assert len(respx_mock.calls) == 1


@pytest.mark.asyncio
async def test_search_tolerates_non_json_response(respx_mock) -> None:
    import respx

    respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(
            200,
            text="<html><body>maintenance</body></html>",
            headers={"Content-Type": "text/html"},
        ),
    )

    result = await _provider().search("8.8.8.8", SearchParams(num_results=5))

    assert result.results == []
