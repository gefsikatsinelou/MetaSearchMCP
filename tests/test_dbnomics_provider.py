"""Unit tests for the DBnomics economic dataset search provider."""

from __future__ import annotations

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.dbnomics import DBnomicsProvider

_API_URL = "https://api.db.nomics.world/v22/search"
_DATASET_BASE = "https://db.nomics.world"


def _doc(code: str = "DSD_EAG_LSO_EA@DF_LSO_NEAC_ALL", **overrides) -> dict:
    """A DBnomics dataset document with sensible defaults."""
    doc = {
        "code": code,
        "name": "National Educational Attainment Classification",
        "description": "Labour market status by educational attainment.",
        "provider_code": "OECD",
        "provider_name": "Organisation for Economic Co-operation and Development",
        "nb_series": 893103,
        "nb_matching_series": 276177,
        "indexed_at": "2026-06-13T07:06:19.814Z",
        "updated_at": "2026-06-11T00:00:00Z",
    }
    doc.update(overrides)
    return doc


def _payload(*docs: dict) -> dict:
    """A DBnomics search response body containing the given documents."""
    return {
        "results": {
            "docs": list(docs),
            "limit": len(docs),
            "num_found": len(docs),
            "offset": 0,
        }
    }


def _provider() -> DBnomicsProvider:
    """Return a fresh provider instance for each test."""
    return DBnomicsProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "dbnomics"
    assert p.tags == ["data", "datasets", "finance", "reference"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "dbnomics" in registry
    assert registry["dbnomics"].tags == ["data", "datasets", "finance", "reference"]


def test_parse_builds_structured_result() -> None:
    p = _provider()
    result = p._parse(_payload(_doc()))

    assert len(result.results) == 1
    hit = result.results[0]
    assert hit.title == "National Educational Attainment Classification"
    assert hit.url == f"{_DATASET_BASE}/OECD/DSD_EAG_LSO_EA@DF_LSO_NEAC_ALL"
    assert hit.source == "db.nomics.world"
    assert hit.provider == "dbnomics"
    assert hit.rank == 1
    assert hit.published_date == "2026-06-11"
    assert hit.snippet == (
        "Organisation for Economic Co-operation and Development | "
        "893103 series | Labour market status by educational attainment."
    )
    assert hit.extra == {
        "code": "DSD_EAG_LSO_EA@DF_LSO_NEAC_ALL",
        "provider_code": "OECD",
        "provider_name": "Organisation for Economic Co-operation and Development",
        "nb_series": 893103,
        "nb_matching_series": 276177,
    }


def test_parse_ranks_sequentially_across_records() -> None:
    p = _provider()
    second = _doc(code="SECOND", name="Second dataset")
    result = p._parse(_payload(_doc(), second))

    assert [r.rank for r in result.results] == [1, 2]
    assert [r.title for r in result.results] == [
        "National Educational Attainment Classification",
        "Second dataset",
    ]


def test_parse_skips_missing_or_empty_items() -> None:
    p = _provider()
    blank_code = _doc(code="", name="No code")
    payload = {"results": {"docs": [_doc(), None, blank_code]}}

    result = p._parse(payload)

    assert [r.extra["code"] for r in result.results] == [
        "DSD_EAG_LSO_EA@DF_LSO_NEAC_ALL"
    ]
    assert result.results[0].rank == 1


def test_parse_name_falls_back_to_code() -> None:
    p = _provider()
    result = p._parse(_payload(_doc(name="")))

    assert result.results[0].title == "DSD_EAG_LSO_EA@DF_LSO_NEAC_ALL"


def test_parse_url_falls_back_without_provider_code() -> None:
    p = _provider()
    result = p._parse(_payload(_doc(provider_code="")))

    hit = result.results[0]
    assert hit.extra["provider_code"] is None
    assert hit.url == f"{_DATASET_BASE}/DSD_EAG_LSO_EA@DF_LSO_NEAC_ALL"


def test_parse_published_date_falls_back_to_indexed_at() -> None:
    p = _provider()
    result = p._parse(_payload(_doc(updated_at=None)))

    assert result.results[0].published_date == "2026-06-13"


def test_parse_coerces_string_series_counts() -> None:
    p = _provider()
    result = p._parse(_payload(_doc(nb_series="42", nb_matching_series="7")))

    assert result.results[0].extra["nb_series"] == 42
    assert result.results[0].extra["nb_matching_series"] == 7


def test_parse_empty_payloads() -> None:
    p = _provider()
    assert p._parse({}).results == []
    assert p._parse({"results": {}}).results == []
    assert p._parse({"results": {"docs": "nonsense"}}).results == []
    assert p._parse({"results": {"docs": []}}).results == []


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_payload(_doc())),
    )

    result = await _provider().search("unemployment", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "dbnomics"
    expected_url = f"{_DATASET_BASE}/OECD/DSD_EAG_LSO_EA@DF_LSO_NEAC_ALL"
    assert result.results[0].url == expected_url


@pytest.mark.asyncio
async def test_search_sends_query_and_limit(respx_mock) -> None:
    route = respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_payload(_doc())),
    )

    await _provider().search("  inflation  ", SearchParams(num_results=3))

    params = route.calls.last.request.url.params
    assert params["q"] == "inflation"
    assert params["limit"] == "3"


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_payload()),
    )

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_empty_docs_returns_nothing(respx_mock) -> None:
    respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_payload()),
    )

    result = await _provider().search("zzz-no-match", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_search_raises_on_api_error(respx_mock) -> None:
    respx_mock.get(_API_URL).mock(return_value=respx.MockResponse(500, json={}))

    with pytest.raises(httpx.HTTPStatusError):
        await _provider().search("unemployment", SearchParams(num_results=5))
