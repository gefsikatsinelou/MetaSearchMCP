"""Unit tests for the DailyMed FDA drug label search provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.dailymed import DailyMedProvider

_SEARCH_URL = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json"
_DETAIL_PREFIX = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid="

_PAYLOAD = {
    "data": [
        {
            "spl_version": 14,
            "published_date": "Oct 02, 2026",
            "title": (
                "BACK AND BODY EXTRA STRENGTH (ASPIRIN, CAFFEINE) TABLET, "
                "FILM COATED [L.N.K. INTERNATIONAL, INC.]"
            ),
            "setid": "6d254f3f-8223-4a6e-a3b2-f53f145ff3dc",
        },
        {"title": "Skipped: no setid"},
        {
            "spl_version": 2,
            "published_date": "not-a-date",
            "title": "SIMPLE LABEL [EXAMPLES PHARMA]",
            "setid": "e51fc0d6-9b32-478c-bab7-328013e692b0",
        },
    ],
    "metadata": {"total_elements": 1065, "current_page": 1},
}


def _mock(respx_mock, payload: object = _PAYLOAD):
    """Mock the DailyMed search endpoint with *payload*."""
    return respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=payload),
    )


def _provider() -> DailyMedProvider:
    """Return a fresh provider instance for each test."""
    return DailyMedProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "dailymed"
    assert p.tags == ["drugs", "pharma", "medical", "health", "web"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "dailymed" in registry
    assert registry["dailymed"].tags == ["drugs", "pharma", "medical", "health", "web"]


@pytest.mark.asyncio
async def test_search_builds_structured_result(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("aspirin", SearchParams(num_results=10))
    first = result.results[0]

    assert first.title.startswith("BACK AND BODY EXTRA STRENGTH")
    assert first.url == f"{_DETAIL_PREFIX}6d254f3f-8223-4a6e-a3b2-f53f145ff3dc"
    assert first.source == "dailymed.nlm.nih.gov"
    assert first.provider == "dailymed"
    assert first.rank == 1
    assert first.published_date == "2026-10-02"
    assert first.snippet == (
        "Ingredients: ASPIRIN, CAFFEINE | "
        "Labeler: L.N.K. INTERNATIONAL, INC. | "
        "SPL version: 14 | Published: 2026-10-02"
    )
    assert first.extra == {
        "setid": "6d254f3f-8223-4a6e-a3b2-f53f145ff3dc",
        "spl_version": 14,
        "labeler": "L.N.K. INTERNATIONAL, INC.",
        "ingredients": "ASPIRIN, CAFFEINE",
        "published_date_raw": "Oct 02, 2026",
    }


@pytest.mark.asyncio
async def test_search_skips_incomplete_and_handles_bad_date(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("aspirin", SearchParams(num_results=10))

    assert [r.rank for r in result.results] == [1, 2]
    second = result.results[1]
    assert second.title == "SIMPLE LABEL [EXAMPLES PHARMA]"
    assert second.published_date is None
    assert second.snippet == ("Labeler: EXAMPLES PHARMA | SPL version: 2")
    assert second.extra["ingredients"] is None


@pytest.mark.asyncio
async def test_search_deduplicates_by_setid(respx_mock) -> None:
    duplicate = {
        "spl_version": 1,
        "title": "Same label",
        "setid": "dup-setid",
    }
    _mock(respx_mock, {"data": [dict(duplicate), dict(duplicate)]})

    result = await _provider().search("same", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["Same label"]


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("aspirin", SearchParams(num_results=1))

    assert len(result.results) == 1
    assert result.results[0].rank == 1


@pytest.mark.asyncio
async def test_search_sends_query_params(respx_mock) -> None:
    route = _mock(respx_mock)

    await _provider().search("metformin", SearchParams(num_results=7))

    params = route.calls.last.request.url.params
    assert params["drug_name"] == "metformin"
    assert params["pagesize"] == "7"


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    route = _mock(respx_mock)

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_handles_unexpected_payload_shapes(respx_mock) -> None:
    for payload in (
        ["not", "a", "mapping"],
        {},
        {"data": None},
        {"data": "nope"},
        {"data": [None, "not-a-mapping"]},
    ):
        respx_mock.get(_SEARCH_URL).mock(
            return_value=respx.MockResponse(200, json=payload),
        )
        result = await _provider().search("aspirin", SearchParams(num_results=5))
        assert result.results == []


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("aspirin", SearchParams(num_results=5))
