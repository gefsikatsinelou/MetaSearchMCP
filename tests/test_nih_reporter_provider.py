"""Unit tests for the NIH RePORTER funded-research-project provider."""

from __future__ import annotations

import json

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.nih_reporter import NihReporterProvider

_API_URL = "https://api.reporter.nih.gov/v2/projects/search"

# Research project grant: fully populated record with its own detail URL.
_GRANT_ABSTRACT = (
    "Malaria due to Plasmodium falciparum remains a highly lethal disease, "
    "and new vaccines are needed."
)

_GRANT = {
    "appl_id": 11508929,
    "fiscal_year": 2026,
    "project_num": "3R01AI195195-01S1",
    "core_project_num": "R01AI195195",
    "project_title": "Perennial Malaria Chemoprevention in the Malaria Vaccine Era",
    "abstract_text": _GRANT_ABSTRACT,
    "award_amount": 692210,
    "agency_code": "NIH",
    "activity_code": "R01",
    "agency_ic_admin": {
        "code": "AI",
        "abbreviation": "NIAID",
        "name": "National Institute of Allergy and Infectious Diseases",
    },
    "organization": {
        "org_name": "STANFORD UNIVERSITY",
        "org_city": "STANFORD",
        "org_state": "CA",
    },
    "principal_investigators": [
        {"full_name": "Prasanna  Jagannathan", "is_contact_pi": True},
    ],
    "project_start_date": "2026-05-01T00:00:00",
    "project_end_date": "2033-04-30T00:00:00",
    "opportunity_number": "PAR-23-084",
    "award_notice_date": "2026-06-09T00:00:00",
    "project_detail_url": "https://reporter.nih.gov/project-details/11508929",
}

# Career award with sparse metadata: no awarding institute, no organization, no
# award amount, no end date -- the integer appl_id is the only link source.
_FELLOW = {
    "appl_id": 11378705,
    "fiscal_year": None,
    "project_num": "5K99AI190129-02",
    "core_project_num": "K99AI190129",
    "project_title": "Hemozoin and liver stage malaria vaccine efficacy",
    "abstract_text": None,
    "award_amount": None,
    "agency_code": "NIH",
    "activity_code": "K99",
    "agency_ic_admin": None,
    "organization": None,
    "principal_investigators": [
        {"full_name": "Ada  Lovelace"},
        {"full_name": "Grace  Hopper"},
        {"full_name": "Alan  Turing"},
        {"full_name": "Katherine  Johnson"},
    ],
    "project_start_date": "2024-09-01T00:00:00",
    "project_end_date": None,
    "opportunity_number": None,
    "award_notice_date": None,
    "project_detail_url": None,
}


def _provider() -> NihReporterProvider:
    """Return a fresh provider instance for each test."""
    return NihReporterProvider()


def _payload(items: object, total: int | None = None) -> dict[str, object]:
    """Wrap *items* in a RePORTER search response envelope."""
    count = len(items) if isinstance(items, list) else 0
    return {
        "meta": {"total": count if total is None else total, "offset": 0, "limit": 25},
        "results": items,
    }


def _mock_search(respx_mock, payload: object = None):
    """Register a RePORTER search route and return it."""
    if payload is None:
        payload = _payload([_GRANT, _FELLOW])
    return respx_mock.post(_API_URL).mock(
        return_value=respx.MockResponse(200, json=payload),
    )


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "nih_reporter"
    assert p.tags == ["academic", "medical", "gov", "funding"]
    assert "keyless" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "nih_reporter" in registry
    assert registry["nih_reporter"].tags == ["academic", "medical", "gov", "funding"]


def test_clean_collapses_whitespace() -> None:
    assert NihReporterProvider._clean("  a\n b\tc ") == "a b c"
    assert NihReporterProvider._clean(None) == ""
    assert NihReporterProvider._clean("") == ""
    assert NihReporterProvider._clean(2026) == "2026"


def test_date_extracts_iso_prefix() -> None:
    assert NihReporterProvider._date("2026-05-01T00:00:00") == "2026-05-01"
    assert NihReporterProvider._date("2026-05-01") == "2026-05-01"
    assert NihReporterProvider._date(None) == ""
    assert NihReporterProvider._date(20260501) == ""


def test_pis_skip_malformed_entries() -> None:
    assert NihReporterProvider._pis(_GRANT) == ["Prasanna Jagannathan"]
    assert NihReporterProvider._pis(
        {"principal_investigators": [{"full_name": " x "}, "nope", {"full_name": ""}]}
    ) == ["x"]
    assert NihReporterProvider._pis({}) == []


def test_organization_prefers_state_over_city() -> None:
    assert NihReporterProvider._organization(_GRANT) == ("STANFORD UNIVERSITY", "CA")
    overseas = {
        "organization": {"org_name": "UNIVERSITE DE GENEVE", "org_city": "GENEVE"}
    }
    assert NihReporterProvider._organization(overseas) == (
        "UNIVERSITE DE GENEVE",
        "GENEVE",
    )
    assert NihReporterProvider._organization({"organization": []}) == ("", "")
    assert NihReporterProvider._organization({}) == ("", "")


def test_agency_reads_awarding_institute() -> None:
    assert NihReporterProvider._agency(_GRANT) == (
        "NIAID",
        "National Institute of Allergy and Infectious Diseases",
    )
    assert NihReporterProvider._agency({}) == ("", "")


def test_award_formats_numeric_amounts() -> None:
    assert NihReporterProvider._award(692210) == "$692,210"
    assert NihReporterProvider._award(692210.0) == "$692,210"
    assert NihReporterProvider._award(0) == "$0"
    assert NihReporterProvider._award(None) == ""
    assert NihReporterProvider._award("692210") == ""
    assert NihReporterProvider._award(True) == ""


def test_build_result_skips_titleless_records() -> None:
    assert _provider()._build_result({}) is None
    assert _provider()._build_result({"project_title": "   "}) is None


def test_parse_respects_limit_and_dedupes() -> None:
    payload = _payload([_GRANT, dict(_GRANT), _FELLOW, "junk", {}])

    results = _provider()._parse(payload, limit=10)

    assert [r.title for r in results] == [
        "Perennial Malaria Chemoprevention in the Malaria Vaccine Era",
        "Hemozoin and liver stage malaria vaccine efficacy",
    ]
    assert [r.rank for r in results] == [1, 2]
    assert len(_provider()._parse(payload, limit=1)) == 1


def test_parse_handles_unexpected_payload_shapes() -> None:
    p = _provider()
    assert p._parse(["not", "a", "mapping"], limit=5) == []
    assert p._parse({"results": "nope"}, limit=5) == []
    assert p._parse({}, limit=5) == []


@pytest.mark.asyncio
async def test_search_builds_grant_result(respx_mock) -> None:
    _mock_search(respx_mock)

    result = await _provider().search("malaria vaccine", SearchParams(num_results=10))
    grant = result.results[0]

    assert grant.title == (
        "Perennial Malaria Chemoprevention in the Malaria Vaccine Era"
    )
    assert grant.url == "https://reporter.nih.gov/project-details/11508929"
    assert grant.source == "reporter.nih.gov"
    assert grant.provider == "nih_reporter"
    assert grant.published_date == "2026-05-01"
    assert grant.snippet == (
        "Prasanna Jagannathan | FY 2026 | NIAID R01 | Award: $692,210 | "
        "Organization: STANFORD UNIVERSITY, CA | "
        "Project period: 2026-05-01 to 2033-04-30 | "
        f"Abstract: {_GRANT_ABSTRACT}"
    )
    assert grant.extra == {
        "appl_id": 11508929,
        "project_num": "3R01AI195195-01S1",
        "core_project_num": "R01AI195195",
        "fiscal_year": 2026,
        "award_amount": 692210,
        "agency": "NIAID",
        "agency_name": "National Institute of Allergy and Infectious Diseases",
        "activity_code": "R01",
        "organization": "STANFORD UNIVERSITY",
        "organization_location": "CA",
        "principal_investigators": ["Prasanna Jagannathan"],
        "project_start_date": "2026-05-01",
        "project_end_date": "2033-04-30",
        "opportunity_number": "PAR-23-084",
        "award_notice_date": "2026-06-09",
        "abstract": _GRANT_ABSTRACT,
    }


@pytest.mark.asyncio
async def test_search_builds_sparse_award_result(respx_mock) -> None:
    _mock_search(respx_mock)

    result = await _provider().search("hemozoin", SearchParams(num_results=10))
    fellow = result.results[1]

    assert fellow.title == "Hemozoin and liver stage malaria vaccine efficacy"
    # No detail URL on the record: the application id builds the landing page.
    assert fellow.url == "https://reporter.nih.gov/project-details/11378705"
    assert fellow.published_date == "2024-09-01"
    assert fellow.snippet == (
        "Ada Lovelace, Grace Hopper, Alan Turing, et al. | NIH K99 | "
        "Project period: 2024-09-01"
    )
    assert fellow.extra["agency"] == "NIH"
    assert fellow.extra["agency_name"] is None
    assert fellow.extra["fiscal_year"] is None
    assert fellow.extra["award_amount"] is None
    assert fellow.extra["organization"] is None
    assert fellow.extra["project_end_date"] is None
    assert fellow.extra["award_notice_date"] is None
    assert fellow.extra["abstract"] is None
    assert len(fellow.extra["principal_investigators"]) == 4


@pytest.mark.asyncio
async def test_search_posts_search_criteria(respx_mock) -> None:
    route = _mock_search(respx_mock)

    await _provider().search("  malaria vaccine  ", SearchParams(num_results=5))

    body = json.loads(route.calls[-1].request.content)
    assert body["criteria"]["advanced_text_search"] == {
        "operator": "and",
        "search_field": "all",
        "search_text": "malaria vaccine",
    }
    assert body["offset"] == 0
    assert body["limit"] == 5
    assert "ProjectTitle" in body["include_fields"]
    assert "AwardAmount" in body["include_fields"]


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    _mock_search(respx_mock)

    result = await _provider().search("malaria", SearchParams(num_results=1))

    assert len(result.results) == 1
    assert result.results[0].rank == 1


@pytest.mark.asyncio
async def test_search_blank_query_skips_requests(respx_mock) -> None:
    route = _mock_search(respx_mock)

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_reports_no_matches_as_empty_page(respx_mock) -> None:
    _mock_search(respx_mock, _payload([], total=0))

    result = await _provider().search("zzzz", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_search_raises_on_server_error(respx_mock) -> None:
    respx_mock.post(_API_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("malaria", SearchParams(num_results=5))


@pytest.mark.asyncio
async def test_snippet_is_truncated_to_shared_limit(respx_mock) -> None:
    long_abstract = " ".join(["malaria"] * 200)
    item = dict(_GRANT, abstract_text=long_abstract)
    _mock_search(respx_mock, _payload([item]))

    result = await _provider().search("malaria", SearchParams(num_results=5))

    snippet = result.results[0].snippet
    assert len(snippet) <= 400
    assert snippet.startswith("Prasanna Jagannathan | FY 2026 | NIAID R01 |")
    assert "| Abstract: malaria malaria" in snippet
