"""Unit tests for the USAspending federal award provider."""

from __future__ import annotations

import json

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH
from metasearchmcp.providers.usaspending import UsaSpendingProvider

_SEARCH_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
_CONTRACTS = ("A", "B", "C", "D")
_GRANTS = ("02", "03", "04", "05")

_CONTRACT = {
    "internal_id": 291386478,
    "Award ID": "7200AA22C00044",
    "Recipient Name": "CHEMONICS INTERNATIONAL, INC.",
    "Award Amount": 67372443.03,
    "Description": "GREEN RECOVERY INVESTMENT PLATFORM:\nUSAID climate programme.",
    "Start Date": "2022-09-21",
    "End Date": "2025-02-11",
    "Awarding Agency": "Agency for International Development",
    "Awarding Sub Agency": "Agency for International Development",
    "Funding Agency": "Agency for International Development",
    "Award Type": None,
    "Contract Award Type": "DEFINITIVE CONTRACT",
    "generated_internal_id": "CONT_AWD_7200AA22C00044_7200_-NONE-_-NONE-",
    "recipient_id": "71710641-1c0a-d4c7-a593-1c039ee88fa2-C",
    "agency_slug": "agency-for-international-development",
}

_GRANT = {
    "internal_id": 268330635,
    "Award ID": "MA-2024-002",
    "Recipient Name": "MASSACHUSETTS BAY TRANSPORTATION AUTHORITY",
    "Award Amount": "169,855,440.00",
    "Description": "THIS PROJECT FUNDS THE PROCUREMENT OF 102 LIGHT RAIL CARS.",
    "Start Date": "2024-01-05",
    "End Date": "2028-12-31",
    "Awarding Agency": "Department of Transportation",
    "Awarding Sub Agency": "Federal Transit Administration",
    "Funding Agency": "Department of Transportation",
    "Award Type": "FORMULA GRANT (A)",
    "Contract Award Type": None,
    "generated_internal_id": "ASST_NON_MA-2024-002_069",
    "recipient_id": "3c326c64-8c0a-e5b2-d2fc-f86d35b41baf-C",
    "agency_slug": "department-of-transportation",
}


def _payload(hits: list[dict]) -> dict:
    """Wrap *hits* in the shape the award search endpoint returns."""
    return {
        "spending_level": "awards",
        "limit": len(hits),
        "results": hits,
        "page_metadata": {"page": 1, "hasNext": False},
        "messages": [],
    }


def _mock(respx_mock, contracts=(), grants=(), status: int = 200):
    """Mock the award endpoint, answering each award-type group its payload."""
    by_group = {
        _CONTRACTS: _payload(list(contracts)),
        _GRANTS: _payload(list(grants)),
    }

    def responder(request):
        codes = tuple(json.loads(request.content)["filters"]["award_type_codes"])
        return respx.MockResponse(status, json=by_group[codes])

    return respx_mock.post(_SEARCH_URL).mock(side_effect=responder)


def _mock_payload(respx_mock, payload: object):
    """Mock the endpoint with the same payload for every award-type group."""
    return respx_mock.post(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=payload),
    )


def _provider() -> UsaSpendingProvider:
    """Return a fresh provider instance for each test."""
    return UsaSpendingProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "usaspending"
    assert p.tags == ["finance", "gov", "funding", "web"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "usaspending" in registry
    assert registry["usaspending"].tags == ["finance", "gov", "funding", "web"]


@pytest.mark.asyncio
async def test_search_builds_result_from_contract(respx_mock) -> None:
    _mock(respx_mock, contracts=[_CONTRACT])

    result = await _provider().search("climate change", SearchParams(num_results=4))
    award = result.results[0]

    assert award.title == "CHEMONICS INTERNATIONAL, INC. — 7200AA22C00044"
    assert award.url == (
        "https://www.usaspending.gov/award/CONT_AWD_7200AA22C00044_7200_-NONE-_-NONE-"
    )
    assert award.source == "usaspending.gov"
    assert award.provider == "usaspending"
    assert award.rank == 1
    assert award.published_date == "2022-09-21"
    assert award.snippet == (
        "Recipient: CHEMONICS INTERNATIONAL, INC. | "
        "Agency for International Development | Award: $67,372,443 | "
        "2022-09-21 to 2025-02-11 | DEFINITIVE CONTRACT | "
        "GREEN RECOVERY INVESTMENT PLATFORM: USAID climate programme."
    )
    assert award.extra == {
        "award_id": "7200AA22C00044",
        "award_group": "contracts",
        "recipient": "CHEMONICS INTERNATIONAL, INC.",
        "recipient_id": "71710641-1c0a-d4c7-a593-1c039ee88fa2-C",
        "amount": 67372443.03,
        "award_type": "DEFINITIVE CONTRACT",
        "awarding_agency": "Agency for International Development",
        "awarding_sub_agency": "Agency for International Development",
        "funding_agency": "Agency for International Development",
        "start_date": "2022-09-21",
        "end_date": "2025-02-11",
        "description": "GREEN RECOVERY INVESTMENT PLATFORM: USAID climate programme.",
        "agency_slug": "agency-for-international-development",
        "generated_internal_id": "CONT_AWD_7200AA22C00044_7200_-NONE-_-NONE-",
    }


@pytest.mark.asyncio
async def test_search_merges_contracts_and_grants(respx_mock) -> None:
    _mock(respx_mock, contracts=[_CONTRACT], grants=[_GRANT])

    result = await _provider().search("transit", SearchParams(num_results=4))

    assert [r.extra["award_group"] for r in result.results] == ["contracts", "grants"]
    assert [r.rank for r in result.results] == [1, 2]

    grant = result.results[1]
    assert grant.title == "MASSACHUSETTS BAY TRANSPORTATION AUTHORITY — MA-2024-002"
    assert grant.url == "https://www.usaspending.gov/award/ASST_NON_MA-2024-002_069"
    # Assistance rows carry their type in "Award Type" rather than the
    # contract-specific field, and the sub-agency qualifies the agency.
    assert grant.extra["award_type"] == "FORMULA GRANT (A)"
    assert grant.snippet.startswith(
        "Recipient: MASSACHUSETTS BAY TRANSPORTATION AUTHORITY | "
        "Department of Transportation (Federal Transit Administration) | "
        "Award: $169,855,440"
    )
    # Amounts arrive as strings with thousands separators.
    assert grant.extra["amount"] == 169855440.0


@pytest.mark.asyncio
async def test_search_splits_limit_between_groups(respx_mock) -> None:
    route = _mock(respx_mock, contracts=[_CONTRACT], grants=[_GRANT])

    await _provider().search("climate", SearchParams(num_results=4))

    assert len(route.calls) == 2
    bodies = [json.loads(call.request.content) for call in route.calls]
    assert [body["limit"] for body in bodies] == [2, 2]
    assert [tuple(body["filters"]["award_type_codes"]) for body in bodies] == [
        _CONTRACTS,
        _GRANTS,
    ]


@pytest.mark.asyncio
async def test_search_sends_expected_request_body(respx_mock) -> None:
    route = _mock(respx_mock, contracts=[_CONTRACT])

    await _provider().search("  climate   change  ", SearchParams(num_results=2))

    body = json.loads(route.calls[0].request.content)
    assert body["filters"]["keywords"] == ["climate change"]
    assert body["page"] == 1
    # The API rejects a sort key missing from the requested fields.
    assert "Award Amount" in body["fields"]
    assert body["sort"] == "Award Amount"
    assert body["order"] == "desc"
    assert body["subawards"] is False


@pytest.mark.asyncio
async def test_search_blank_query_skips_requests(respx_mock) -> None:
    route = _mock(respx_mock, contracts=[_CONTRACT])

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_skips_hits_without_title_or_url(respx_mock) -> None:
    _mock(
        respx_mock,
        contracts=[
            # No award id at all: nothing can be linked, so the hit is dropped.
            {"Recipient Name": "NO LINK CORP", "Award Amount": 1000},
            # No generated id, but the award id still yields a fallback link.
            {"Award ID": "A2", "Recipient Name": "NO ID CORP"},
            # Neither a recipient nor an id leaves no usable title.
            {"Award Amount": 2000, "generated_internal_id": "AWD_A3"},
            "not-a-mapping",
        ],
    )

    result = await _provider().search("award", SearchParams(num_results=4))

    assert [r.title for r in result.results] == ["NO ID CORP — A2"]
    assert result.results[0].url == "https://www.usaspending.gov/search?keyword=A2"


@pytest.mark.asyncio
async def test_search_deduplicates_by_generated_id(respx_mock) -> None:
    _mock(respx_mock, contracts=[_CONTRACT, dict(_CONTRACT)])

    result = await _provider().search("climate", SearchParams(num_results=4))

    assert [r.extra["award_group"] for r in result.results] == ["contracts"]


@pytest.mark.asyncio
async def test_search_handles_unexpected_payload_shapes(respx_mock) -> None:
    for payload in (
        ["not", "a", "mapping"],
        {},
        {"results": None},
        {"results": "nope"},
        {"results": ["not-a-mapping", {}]},
    ):
        _mock_payload(respx_mock, payload)
        result = await _provider().search("climate", SearchParams(num_results=4))
        assert result.results == []


@pytest.mark.asyncio
async def test_search_truncates_long_snippet(respx_mock) -> None:
    hit = dict(_CONTRACT, Description=" ".join(["appropriation"] * 100))
    _mock(respx_mock, contracts=[hit])

    result = await _provider().search("climate", SearchParams(num_results=4))

    assert len(result.results[0].snippet) <= MAX_SNIPPET_LENGTH


@pytest.mark.asyncio
async def test_search_handles_missing_amounts_and_invalid_types(respx_mock) -> None:
    _mock(
        respx_mock,
        contracts=[
            dict(
                _CONTRACT,
                **{
                    "Award Amount": None,
                    "Contract Award Type": 12345,
                    "Start Date": "",
                },
            ),
        ],
    )

    result = await _provider().search("climate", SearchParams(num_results=4))
    award = result.results[0]

    assert award.extra["amount"] is None
    # Non-string labels are ignored rather than copied into the result.
    assert award.extra["award_type"] is None
    assert award.extra["start_date"] is None
    assert award.published_date is None
    assert "Award:" not in award.snippet


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    _mock(respx_mock, contracts=[_CONTRACT], status=503)

    with pytest.raises(HTTPStatusError):
        await _provider().search("climate", SearchParams(num_results=4))
