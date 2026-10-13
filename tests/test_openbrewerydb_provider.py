"""Unit tests for the Open Brewery DB brewery search provider."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.openbrewerydb import OpenBreweryDbProvider

_ENDPOINT = "https://api.openbrewerydb.org/v1/breweries/search"
_BREWERY_ID = "78c50e54-34e3-415d-9574-ac0cc0505113"

_BREWERY: dict[str, Any] = {
    "id": _BREWERY_ID,
    "name": "Dog & Pony Alehouse and Grill",
    "brewery_type": "brewpub",
    "address_1": "351 Park Ave N",
    "address_2": None,
    "address_3": None,
    "city": "Renton",
    "state_province": "Washington",
    "postal_code": "98057-5716",
    "country": "United States",
    "longitude": -122.2023129,
    "latitude": 47.48758261,
    "phone": "4252548080",
    "website_url": "http://www.thedogandpony.com",
    "state": "Washington",
    "street": "351 Park Ave N",
}

# No website: the result should fall back to the API record URL.
_NO_SITE: dict[str, Any] = {
    "id": "abc-123",
    "name": "Hidden Taproom",
    "brewery_type": "taproom",
    "city": "Berlin",
    "state_province": None,
    "country": "Germany",
    "latitude": None,
    "longitude": None,
    "phone": "",
    "website_url": None,
}

_SPARSE: dict[str, Any] = {"id": "sparse-1"}


def test_openbrewerydb_name_tags_and_availability() -> None:
    p = OpenBreweryDbProvider()
    assert p.name == "openbrewerydb"
    assert p.tags == ["food", "drinks", "places"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_openbrewerydb_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "openbrewerydb" in registry
    assert registry["openbrewerydb"].tags == ["food", "drinks", "places"]


def test_openbrewerydb_parse_record() -> None:
    p = OpenBreweryDbProvider()
    result = p._parse([_BREWERY], limit=5)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Dog & Pony Alehouse and Grill"
    assert r.url == "http://www.thedogandpony.com"
    assert r.source == "openbrewerydb.org"
    assert r.provider == "openbrewerydb"
    assert r.rank == 1
    assert r.published_date is None
    assert r.snippet == "brewpub | Renton, Washington | 4252548080"
    assert r.extra["brewery_id"] == _BREWERY_ID
    assert r.extra["brewery_type"] == "brewpub"
    assert r.extra["address"] == "351 Park Ave N"
    assert r.extra["city"] == "Renton"
    assert r.extra["state"] == "Washington"
    assert r.extra["postal_code"] == "98057-5716"
    assert r.extra["country"] == "United States"
    assert r.extra["phone"] == "4252548080"
    assert r.extra["website"] == "http://www.thedogandpony.com"
    assert r.extra["latitude"] == 47.48758261
    assert r.extra["longitude"] == -122.2023129


def test_openbrewerydb_falls_back_to_record_url_without_website() -> None:
    p = OpenBreweryDbProvider()
    r = p._parse([_NO_SITE]).results[0]

    assert r.title == "Hidden Taproom"
    assert r.url == "https://api.openbrewerydb.org/v1/breweries/abc-123"
    # Non-US country is shown; missing region/phone are omitted.
    assert r.snippet == "taproom | Berlin | Germany"
    assert r.extra["website"] is None
    assert r.extra["state"] is None
    assert r.extra["phone"] is None
    assert r.extra["latitude"] is None
    assert r.extra["longitude"] is None


def test_openbrewerydb_sparse_record_falls_back_to_identifier() -> None:
    p = OpenBreweryDbProvider()
    r = p._parse([_SPARSE]).results[0]

    assert r.title == "Brewery sparse-1"
    assert r.url == "https://api.openbrewerydb.org/v1/breweries/sparse-1"
    assert r.snippet == ""
    assert r.extra["brewery_type"] is None
    assert r.extra["country"] is None
    assert r.extra["city"] is None
    assert r.extra["website"] is None


def test_openbrewerydb_uses_state_fallback_field() -> None:
    p = OpenBreweryDbProvider()
    payload = [{"id": "s1", "city": "Austin", "state": "Texas"}]
    r = p._parse(payload).results[0]

    assert r.snippet == "Austin, Texas"
    assert r.extra["state"] == "Texas"


def test_openbrewerydb_parse_skips_records_without_id() -> None:
    p = OpenBreweryDbProvider()
    payload = [{}, {"id": ""}, {"id": None}, "nope", _BREWERY]
    results = p._parse(payload).results
    assert [r.extra["brewery_id"] for r in results] == [_BREWERY_ID]
    assert results[0].rank == 1


def test_openbrewerydb_parse_respects_limit() -> None:
    p = OpenBreweryDbProvider()
    payload = [_BREWERY, _NO_SITE, _SPARSE]
    assert len(p._parse(payload, limit=2).results) == 2
    assert len(p._parse(payload).results) == 3


def test_openbrewerydb_parse_empty_and_malformed() -> None:
    p = OpenBreweryDbProvider()
    assert p._parse([]).results == []
    assert p._parse({}).results == []
    assert p._parse({"error": "Not Found"}).results == []
    assert p._parse([1, 2, 3]).results == []
    assert p._parse("nope").results == []
    assert p._parse(None).results == []


def test_openbrewerydb_parse_ignores_odd_field_types() -> None:
    p = OpenBreweryDbProvider()
    payload = [
        {
            "id": "7",
            "name": 42,
            "brewery_type": None,
            "city": ["nope"],
            "latitude": True,
            "longitude": "1.5",
            "phone": 123,
        }
    ]
    r = p._parse(payload).results[0]

    assert r.title == "Brewery 7"
    assert r.snippet == ""
    assert r.extra["brewery_type"] is None
    assert r.extra["city"] is None
    assert r.extra["latitude"] is None
    assert r.extra["longitude"] is None
    assert r.extra["phone"] is None


def test_openbrewerydb_helpers() -> None:
    from metasearchmcp.providers.openbrewerydb import _clean, _number

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _clean(42) == ""
    assert _number(47.48) == 47.48
    assert _number(-122) == -122.0
    assert _number(True) is None
    assert _number("1.5") is None
    assert _number(None) is None


async def test_openbrewerydb_search_sends_expected_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=[_BREWERY, _NO_SITE])
    )

    result = await OpenBreweryDbProvider().search(
        "dog",
        SearchParams(num_results=5),
    )

    assert route.called
    params = route.calls[0].request.url.params
    assert params["query"] == "dog"
    assert params["per_page"] == "5"

    assert [r.extra["brewery_id"] for r in result.results] == [_BREWERY_ID, "abc-123"]


async def test_openbrewerydb_search_respects_result_limits(respx_mock) -> None:
    records = [dict(_BREWERY, id=f"b{n}") for n in range(60)]
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(200, json=records))

    provider = OpenBreweryDbProvider()
    provider._max_results = 1000
    result = await provider.search("dog", SearchParams(num_results=50))
    assert len(result.results) == 50

    provider._max_results = 1
    result = await provider.search("dog", SearchParams(num_results=50))
    assert len(result.results) == 1


async def test_openbrewerydb_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT)

    result = await OpenBreweryDbProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_openbrewerydb_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(500))

    with pytest.raises(httpx.HTTPStatusError):
        await OpenBreweryDbProvider().search("dog", SearchParams())
