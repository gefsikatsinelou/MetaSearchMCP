"""Unit tests for the Grants.gov funding-opportunity provider."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.grants_gov import GrantsGovProvider

_SEARCH_URL = "https://api.grants.gov/v1/api/search2"
_DETAIL_URL = "https://api.grants.gov/v1/api/fetchOpportunity"

_HIT = {
    "id": "363852",
    "number": "NOAA-OAR-CPO-2026-33326",
    "title": "Climate Program Office (CPO) FY2026 Earth System Science Partnership",
    "agencyCode": "DOC-DOCNOAAERA",
    "agency": "DOC NOAA - ERA Production",
    "openDate": "09/11/2026",
    "closeDate": "10/26/2026",
    "oppStatus": "posted",
    "docType": "synopsis",
    "cfdaList": ["11.431", "11.431", None],
}

_SHORT_HIT = {
    "id": "363817",
    "number": "W9126G262SOI0520",
    "title": "Groundwater and Surficial Water Salinity Changes",
    "agencyCode": "DOD-COE-FW",
    "agency": "Fort Worth District",
    "openDate": "09/04/2026",
    "closeDate": "",
    "oppStatus": "forecasted",
    "docType": "forecast",
    "cfdaList": None,
}

_SYNOPSIS = {
    "opportunityId": 363852,
    "synopsisDesc": (
        "<p>The Earth System Science and Services Partnership supports\n"
        "  research activities.</p><p>Applications must be submitted online.</p>"
    ),
    "awardCeiling": "10000000",
    "awardFloor": "1",
    "numberOfAwards": 3,
    "costSharing": False,
    "fundingInstruments": [
        {"id": "CA", "description": "Cooperative Agreement"},
        {"id": "G", "description": "Grant"},
        {"id": "PC", "description": "Procurement Contract"},
        {"id": "O", "description": "Other"},
    ],
    "applicantTypes": [
        {"id": "06", "description": "Public and State controlled institutions"},
        {"id": "12", "description": "Nonprofits having a 501(c)(3) status"},
        {"id": "20", "description": "Private institutions of higher education"},
        {"id": "23", "description": "Small businesses"},
    ],
}


def _search_payload(opp_hits: list[Any], hit_count: object = 47) -> dict:
    """Return a Grants.gov search response wrapping *opp_hits*."""
    return {
        "errorcode": 0,
        "msg": "Webservice Succeeds",
        "data": {"hitCount": hit_count, "oppHits": opp_hits},
    }


def _mock_search(respx_mock, payload: object = None):
    """Mock the Grants.gov search endpoint."""
    return respx_mock.post(_SEARCH_URL).mock(
        return_value=respx.MockResponse(
            200,
            json=_search_payload([_HIT, _SHORT_HIT]) if payload is None else payload,
        ),
    )


def _mock_details(respx_mock, synopsis: object = None):
    """Mock every opportunity detail lookup with *synopsis*."""

    def _respond(request: httpx.Request) -> respx.MockResponse:
        opportunity_id = request.url.path.rsplit("/", 1)[-1]
        return respx.MockResponse(
            200,
            json={
                "errorcode": 0,
                "data": {
                    "id": opportunity_id,
                    "synopsis": _SYNOPSIS if synopsis is None else synopsis,
                },
            },
        )

    return respx_mock.post(_DETAIL_URL).mock(side_effect=_respond)


def _provider() -> GrantsGovProvider:
    """Return a fresh provider instance for each test."""
    return GrantsGovProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "grants_gov"
    assert p.tags == ["academic", "gov", "funding", "web"]
    assert "no key" not in p.description
    assert "keyless" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "grants_gov" in registry
    assert registry["grants_gov"].tags == ["academic", "gov", "funding", "web"]


@pytest.mark.asyncio
async def test_search_builds_result_from_opportunity(respx_mock) -> None:
    _mock_search(respx_mock)
    _mock_details(respx_mock)

    result = await _provider().search("climate", SearchParams(num_results=10))
    opportunity = result.results[0]

    assert opportunity.title == _HIT["title"]
    assert opportunity.url == "https://www.grants.gov/search-results-detail/363852"
    assert opportunity.source == "grants.gov"
    assert opportunity.provider == "grants_gov"
    assert opportunity.rank == 1
    assert opportunity.published_date == "2026-09-11"
    # Snippets are capped at MAX_SNIPPET_LENGTH, so the trailing eligibility
    # entry is cut short.
    assert opportunity.snippet == (
        "The Earth System Science and Services Partnership supports research "
        "activities. Applications must be submitted online. | "
        "Agency: DOC NOAA - ERA Production | Status: posted | "
        "Closes: 2026-10-26 | Award: $1 - $10,000,000 | "
        "Instruments: Cooperative Agreement, Grant, Procurement Contract | "
        "Eligible: Public and State controlled institutions, Nonprofits having "
        "a 501(c)(3) status, Private institutions of"
    )
    assert opportunity.extra == {
        "opportunity_id": "363852",
        "opportunity_number": "NOAA-OAR-CPO-2026-33326",
        "agency": "DOC NOAA - ERA Production",
        "agency_code": "DOC-DOCNOAAERA",
        "status": "posted",
        "document_type": "synopsis",
        "open_date": "2026-09-11",
        "close_date": "2026-10-26",
        "cfda_numbers": ["11.431"],
        "award_ceiling": 10000000,
        "award_floor": 1,
        "expected_awards": 3,
        "cost_sharing": False,
        "funding_instruments": [
            "Cooperative Agreement",
            "Grant",
            "Procurement Contract",
        ],
        "eligible_applicants": [
            "Public and State controlled institutions",
            "Nonprofits having a 501(c)(3) status",
            "Private institutions of higher education",
        ],
        "description": (
            "The Earth System Science and Services Partnership supports research "
            "activities. Applications must be submitted online."
        ),
        "total_results": 47,
    }


@pytest.mark.asyncio
async def test_search_reports_hit_without_details(respx_mock) -> None:
    _mock_search(respx_mock)
    _mock_details(respx_mock)

    result = await _provider().search("water", SearchParams(num_results=10))
    forecast = result.results[1]

    assert forecast.title == _SHORT_HIT["title"]
    assert forecast.rank == 2
    # No close date means no publication date either: only openDate is a date.
    assert forecast.published_date == "2026-09-04"
    assert forecast.extra["close_date"] is None
    assert forecast.extra["cfda_numbers"] == []
    assert forecast.extra["document_type"] == "forecast"
    assert forecast.extra["status"] == "forecasted"
    # The detail payload carries no title of its own; the synopsis still applies.
    assert forecast.extra["award_ceiling"] == 10000000
    assert forecast.snippet.startswith("The Earth System Science")


@pytest.mark.asyncio
async def test_search_degrades_when_detail_lookup_fails(respx_mock) -> None:
    _mock_search(respx_mock)
    respx_mock.post(_DETAIL_URL).mock(side_effect=httpx.ConnectError("boom"))

    result = await _provider().search("climate", SearchParams(num_results=10))

    assert [r.title for r in result.results] == [_HIT["title"], _SHORT_HIT["title"]]
    first = result.results[0]
    assert first.extra["description"] is None
    assert first.extra["award_ceiling"] is None
    assert first.snippet == (
        "Agency: DOC NOAA - ERA Production | Status: posted | Closes: 2026-10-26"
    )


@pytest.mark.asyncio
async def test_search_ignores_error_detail_payload(respx_mock) -> None:
    _mock_search(respx_mock)
    respx_mock.post(_DETAIL_URL).mock(
        return_value=respx.MockResponse(
            200,
            json={"errorcode": 1, "msg": "Invalid opportunity", "data": None},
        ),
    )

    result = await _provider().search("climate", SearchParams(num_results=10))

    assert len(result.results) == 2
    assert result.results[0].extra["description"] is None


@pytest.mark.asyncio
async def test_search_skips_incomplete_and_malformed_entries(respx_mock) -> None:
    _mock_search(
        respx_mock,
        _search_payload(
            [
                _HIT,
                {"id": "1", "title": "   "},
                {"title": "No id"},
                "not-a-mapping",
            ],
        ),
    )
    _mock_details(respx_mock)

    result = await _provider().search("climate", SearchParams(num_results=10))

    assert [r.title for r in result.results] == [_HIT["title"]]
    assert [r.rank for r in result.results] == [1]


@pytest.mark.asyncio
async def test_search_deduplicates_by_opportunity_id(respx_mock) -> None:
    _mock_search(respx_mock, _search_payload([_HIT, dict(_HIT)]))
    _mock_details(respx_mock)

    result = await _provider().search("climate", SearchParams(num_results=5))

    assert [r.title for r in result.results] == [_HIT["title"]]


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    _mock_search(respx_mock, _search_payload([_HIT, _SHORT_HIT]))
    route = _mock_details(respx_mock)

    result = await _provider().search("climate", SearchParams(num_results=1))

    assert [r.title for r in result.results] == [_HIT["title"]]
    # Only the reported hit needs a detail lookup.
    assert len(route.calls) == 1


@pytest.mark.asyncio
async def test_search_fetches_details_for_leading_hits_only(respx_mock) -> None:
    hits = [dict(_HIT, id=str(1000 + index)) for index in range(8)]
    _mock_search(respx_mock, _search_payload(hits))
    route = _mock_details(respx_mock)

    result = await _provider().search("climate", SearchParams(num_results=8))

    assert len(result.results) == 8
    assert len(route.calls) == 5
    # Hits past the detail limit keep the search-API fields.
    assert result.results[7].extra["description"] is None
    assert result.results[7].extra["award_ceiling"] is None


@pytest.mark.asyncio
async def test_search_sends_keyword_rows_and_status_filter(respx_mock) -> None:
    route = _mock_search(respx_mock, _search_payload([]))
    details = _mock_details(respx_mock)

    await _provider().search("quantum computing", SearchParams(num_results=7))

    assert json.loads(route.calls.last.request.content) == {
        "keyword": "quantum computing",
        "rows": 7,
        "oppStatuses": "forecasted|posted",
    }
    # No hits means no detail lookup at all.
    assert not details.called


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    route = _mock_search(respx_mock)
    details = _mock_details(respx_mock)

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called
    assert not details.called


@pytest.mark.asyncio
async def test_search_handles_unexpected_payload_shapes(respx_mock) -> None:
    details = _mock_details(respx_mock)
    payloads: list[object] = [
        ["not", "a", "mapping"],
        {},
        {"data": None},
        {"data": {"oppHits": "nope"}},
    ]
    for payload in payloads:
        respx_mock.post(_SEARCH_URL).mock(
            return_value=respx.MockResponse(200, json=payload),
        )
        result = await _provider().search("climate", SearchParams(num_results=5))
        assert result.results == []
    assert not details.called


@pytest.mark.asyncio
async def test_search_raises_on_api_error(respx_mock) -> None:
    respx_mock.post(_SEARCH_URL).mock(
        return_value=respx.MockResponse(
            200,
            json={"errorcode": 1, "msg": "Invalid search parameters", "data": None},
        ),
    )

    with pytest.raises(RuntimeError, match="Invalid search parameters"):
        await _provider().search("climate", SearchParams(num_results=5))


@pytest.mark.asyncio
async def test_search_handles_unexpected_detail_shapes(respx_mock) -> None:
    _mock_search(respx_mock, _search_payload([_HIT]))
    respx_mock.post(_DETAIL_URL).mock(
        return_value=respx.MockResponse(200, json={"data": {"synopsis": "nope"}}),
    )

    result = await _provider().search("climate", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].extra["description"] is None
    assert result.results[0].extra["total_results"] == 47


@pytest.mark.asyncio
async def test_search_without_total_reports_none(respx_mock) -> None:
    _mock_search(respx_mock, {"errorcode": 0, "data": {"oppHits": [_HIT]}})
    _mock_details(respx_mock)

    result = await _provider().search("climate", SearchParams(num_results=5))

    assert result.results[0].extra["total_results"] is None


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.post(_SEARCH_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("climate", SearchParams(num_results=5))
