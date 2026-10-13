"""Unit tests for the Hipolabs universities search provider."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.universities import UniversitiesProvider

_ENDPOINT = "http://universities.hipolabs.com/search"

_STANFORD: dict[str, Any] = {
    "country": "United States",
    "alpha_two_code": "US",
    "state-province": None,
    "web_pages": ["http://www.stanford.edu/"],
    "name": "Stanford University",
    "domains": ["stanford.edu"],
}

# No website: the result should fall back to the first domain.
_NO_SITE: dict[str, Any] = {
    "country": "Canada",
    "alpha_two_code": "CA",
    "state-province": "Alberta",
    "web_pages": [],
    "name": "Northern Alberta Institute of Technology",
    "domains": ["www.nait.ca"],
}

# No website and no domain: fall back to the search URL itself.
_NO_URL: dict[str, Any] = {
    "country": "Japan",
    "alpha_two_code": "JP",
    "state-province": None,
    "web_pages": [],
    "name": "Example University",
    "domains": None,
}

_SPARSE: dict[str, Any] = {"name": "Sparse College"}


def test_universities_name_tags_and_availability() -> None:
    p = UniversitiesProvider()
    assert p.name == "universities"
    assert p.tags == ["education", "reference", "places"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_universities_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "universities" in registry
    assert registry["universities"].tags == ["education", "reference", "places"]


def test_universities_parse_record() -> None:
    p = UniversitiesProvider()
    result = p._parse([_STANFORD], limit=5)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Stanford University"
    assert r.url == "http://www.stanford.edu/"
    assert r.source == "universities.hipolabs.com"
    assert r.provider == "universities"
    assert r.rank == 1
    assert r.published_date is None
    assert r.snippet == "United States | stanford.edu"
    assert r.extra["country"] == "United States"
    assert r.extra["alpha_two_code"] == "US"
    assert r.extra["state_province"] is None
    assert r.extra["domains"] == ["stanford.edu"]
    assert r.extra["web_pages"] == ["http://www.stanford.edu/"]


def test_universities_falls_back_to_domain_without_website() -> None:
    p = UniversitiesProvider()
    r = p._parse([_NO_SITE]).results[0]

    assert r.title == "Northern Alberta Institute of Technology"
    assert r.url == "https://nait.ca"
    assert r.snippet == "Canada | Alberta | www.nait.ca"
    assert r.extra["state_province"] == "Alberta"
    assert r.extra["web_pages"] is None


def test_universities_falls_back_to_search_url_without_website_or_domain() -> None:
    p = UniversitiesProvider()
    r = p._parse([_NO_URL]).results[0]

    assert r.title == "Example University"
    assert r.url == f"{_ENDPOINT}?name=Example%20University"
    assert r.snippet == "Japan"
    assert r.extra["domains"] is None


def test_universities_sparse_record_keeps_only_name() -> None:
    p = UniversitiesProvider()
    r = p._parse([_SPARSE]).results[0]

    assert r.title == "Sparse College"
    assert r.url == f"{_ENDPOINT}?name=Sparse%20College"
    assert r.snippet == ""
    assert r.extra["country"] is None
    assert r.extra["alpha_two_code"] is None
    assert r.extra["state_province"] is None
    assert r.extra["domains"] is None
    assert r.extra["web_pages"] is None


def test_universities_uses_state_province_underscore_fallback() -> None:
    p = UniversitiesProvider()
    payload = [{"name": "Somewhere U", "state_province": "Texas"}]
    r = p._parse(payload).results[0]

    assert r.snippet == "Texas"
    assert r.extra["state_province"] == "Texas"


def test_universities_parse_skips_records_without_name() -> None:
    p = UniversitiesProvider()
    payload = [{}, {"name": ""}, {"name": None}, "nope", _STANFORD]
    results = p._parse(payload).results
    assert [r.title for r in results] == ["Stanford University"]
    assert results[0].rank == 1


def test_universities_parse_respects_limit() -> None:
    p = UniversitiesProvider()
    payload = [_STANFORD, _NO_SITE, _SPARSE]
    assert len(p._parse(payload, limit=2).results) == 2
    assert len(p._parse(payload).results) == 3


def test_universities_parse_empty_and_malformed() -> None:
    p = UniversitiesProvider()
    assert p._parse([]).results == []
    assert p._parse({}).results == []
    assert p._parse({"error": "Not Found"}).results == []
    assert p._parse([1, 2, 3]).results == []
    assert p._parse("nope").results == []
    assert p._parse(None).results == []


def test_universities_parse_ignores_odd_field_types() -> None:
    p = UniversitiesProvider()
    payload = [
        {
            "name": "Odd U",
            "country": 42,
            "alpha_two_code": None,
            "state-province": ["nope"],
            "domains": "nope",
            "web_pages": [123, "https://odd.example"],
        }
    ]
    r = p._parse(payload).results[0]

    assert r.title == "Odd U"
    assert r.url == "https://odd.example"
    assert r.snippet == ""
    assert r.extra["country"] is None
    assert r.extra["alpha_two_code"] is None
    assert r.extra["state_province"] is None
    assert r.extra["domains"] is None
    assert r.extra["web_pages"] == ["https://odd.example"]


def test_universities_helpers() -> None:
    from metasearchmcp.providers.universities import _clean, _string_list

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _clean(42) == ""
    assert _string_list(["a", "  b ", "", 7]) == ["a", "b"]
    assert _string_list("nope") == []
    assert _string_list(None) == []


async def test_universities_search_sends_expected_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=[_STANFORD, _NO_SITE])
    )

    result = await UniversitiesProvider().search(
        "northern",
        SearchParams(num_results=5),
    )

    assert route.called
    params = route.calls[0].request.url.params
    assert params["name"] == "northern"

    assert [r.title for r in result.results] == [
        "Stanford University",
        "Northern Alberta Institute of Technology",
    ]


async def test_universities_search_respects_result_limits(respx_mock) -> None:
    records = [dict(_STANFORD, name=f"University {n}") for n in range(60)]
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(200, json=records))

    provider = UniversitiesProvider()
    provider._max_results = 1000
    result = await provider.search("university", SearchParams(num_results=30))
    assert len(result.results) == 30

    provider._max_results = 1
    result = await provider.search("university", SearchParams(num_results=30))
    assert len(result.results) == 1


async def test_universities_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT)

    result = await UniversitiesProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_universities_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(500))

    with pytest.raises(httpx.HTTPStatusError):
        await UniversitiesProvider().search("stanford", SearchParams())
