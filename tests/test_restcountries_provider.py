"""Unit tests for the REST Countries search provider."""

from __future__ import annotations

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.restcountries import (
    _API_BASE,
    _FIELDS,
    RestCountriesProvider,
)

_NAME_ROUTE = r"https://restcountries\.com/v3\.1/name/.*"


def _france(**over) -> dict:
    """A REST Countries record with sensible defaults."""
    item = {
        "name": {"common": "France", "official": "French Republic"},
        "cca2": "FR",
        "cca3": "FRA",
        "capital": ["Paris"],
        "region": "Europe",
        "subregion": "Western Europe",
        "population": 67391582,
        "area": 551695.0,
        "currencies": {"EUR": {"name": "Euro", "symbol": "€"}},
        "languages": {"fra": "French"},
        "flags": {"png": "https://flagcdn.com/w320/fr.png"},
    }
    item.update(over)
    return item


def _provider() -> RestCountriesProvider:
    """Return a fresh provider instance for each test."""
    return RestCountriesProvider()


def _mock(respx_mock, payload, status: int = 200):
    """Mock the REST Countries ``/name`` endpoint with *payload*."""
    return respx_mock.get(url__regex=_NAME_ROUTE).mock(
        return_value=respx.MockResponse(status, json=payload),
    )


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "restcountries"
    assert p.tags == ["places", "reference", "geography", "web"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "restcountries" in registry
    assert registry["restcountries"].tags == [
        "places",
        "reference",
        "geography",
        "web",
    ]


def test_items_ignores_malformed_payloads() -> None:
    p = _provider()
    assert p._items([_france()]) == [_france()]
    assert p._items({"results": []}) == []
    assert p._items(None) == []
    assert p._items("nonsense") == []
    assert p._items([_france(), None, "x"]) == [_france()]


def test_build_result_formats_all_facts() -> None:
    built = RestCountriesProvider._build_result(_france(), 1)

    assert built is not None
    assert built.title == "France"
    assert built.url == f"{_API_BASE}/alpha/FR"
    assert built.source == "restcountries.com"
    assert built.provider == "restcountries"
    assert built.rank == 1
    assert built.snippet == (
        "Capital: Paris | Europe / Western Europe | pop. 67,391,582 | "
        "551,695 km² | Euro (€) | lang: French"
    )
    assert built.extra == {
        "cca2": "FR",
        "cca3": "FRA",
        "region": "Europe",
        "subregion": "Western Europe",
        "population": 67391582,
        "flag": "https://flagcdn.com/w320/fr.png",
    }


def test_build_result_falls_back_to_official_name() -> None:
    built = RestCountriesProvider._build_result(
        _france(name={"official": "French Republic"}),
        1,
    )

    assert built is not None
    assert built.title == "French Republic"


def test_build_result_falls_back_to_cca3_for_url() -> None:
    built = RestCountriesProvider._build_result(_france(cca2=""), 1)

    assert built is not None
    assert built.url == f"{_API_BASE}/alpha/FRA"
    assert built.extra["cca2"] == ""


def test_build_result_joins_multiple_capitals() -> None:
    built = RestCountriesProvider._build_result(
        _france(capital=["Pretoria", "Cape Town", "Bloemfontein"]),
        1,
    )

    assert built is not None
    assert "Capital: Pretoria, Cape Town, Bloemfontein" in built.snippet


def test_build_result_skips_missing_name() -> None:
    assert RestCountriesProvider._build_result(_france(name={}), 1) is None
    assert RestCountriesProvider._build_result(_france(name=None), 1) is None


def test_build_result_tolerates_sparse_record() -> None:
    built = RestCountriesProvider._build_result(
        {"name": {"common": "Nowhere"}, "cca2": "NW"},
        1,
    )

    assert built is not None
    assert built.snippet == ""
    assert built.url == f"{_API_BASE}/alpha/NW"


@pytest.mark.asyncio
async def test_search_returns_ranked_results(respx_mock) -> None:
    _mock(respx_mock, [_france(), _france(name={"common": "Germany"}, cca2="DE")])

    result = await _provider().search("united", SearchParams(num_results=10))

    assert [r.title for r in result.results] == ["France", "Germany"]
    assert [r.rank for r in result.results] == [1, 2]
    assert all(r.provider == "restcountries" for r in result.results)


@pytest.mark.asyncio
async def test_search_sends_trimmed_query_and_fields(respx_mock) -> None:
    route = _mock(respx_mock, [_france()])

    await _provider().search("  france  ", SearchParams(num_results=5))

    request = route.calls.last.request
    assert request.url.path == "/v3.1/name/france"
    assert request.url.params["fields"] == _FIELDS


@pytest.mark.asyncio
async def test_search_url_encodes_query(respx_mock) -> None:
    route = _mock(respx_mock, [_france()])

    await _provider().search("new zealand", SearchParams(num_results=5))

    request = route.calls.last.request
    assert request.url.raw_path.split(b"?")[0] == b"/v3.1/name/new%20zealand"


@pytest.mark.asyncio
async def test_search_truncates_to_limit(respx_mock) -> None:
    _mock(
        respx_mock,
        [_france(name={"common": "A"}), _france(name={"common": "B"})],
    )

    result = await _provider().search("x", SearchParams(num_results=1))

    assert [r.rank for r in result.results] == [1]


@pytest.mark.asyncio
async def test_search_blank_query_skips_requests(respx_mock) -> None:
    route = _mock(respx_mock, [_france()])

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_treats_404_as_empty(respx_mock) -> None:
    _mock(respx_mock, {"status": 404, "message": "Not Found"}, status=404)

    result = await _provider().search("zzz", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_search_raises_on_server_error(respx_mock) -> None:
    _mock(respx_mock, {"message": "boom"}, status=500)

    with pytest.raises(httpx.HTTPStatusError):
        await _provider().search("france", SearchParams(num_results=5))
