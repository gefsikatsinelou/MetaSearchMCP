"""Unit tests for the ClinicalTrials.gov clinical trial search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.clinicaltrials import ClinicalTrialsProvider

_RESPONSE = {
    "studies": [
        {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT06461182",
                    "briefTitle": "Ga-68-CXCR4 PET/CT in Indolent B-cell Lymphoma",
                },
                "statusModule": {
                    "overallStatus": "RECRUITING",
                    "completionDateStruct": {"date": "2027-04", "type": "ESTIMATED"},
                },
                "sponsorCollaboratorsModule": {
                    "leadSponsor": {"name": "Koo Foundation Sun Yat-Sen Cancer Center"},
                },
                "descriptionModule": {
                    "briefSummary": "A study about lymphoma imaging.",
                },
                "conditionsModule": {
                    "conditions": ["Indolent B-Cell Non-Hodgkin Lymphoma"],
                },
                "designModule": {"studyType": "INTERVENTIONAL"},
            },
        },
        {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT07397975",
                    "briefTitle": "Speech-based Assessment of Relapse Risk",
                },
                "statusModule": {
                    "overallStatus": "COMPLETED",
                    "completionDateStruct": {"date": "2029-01-31"},
                },
                "sponsorCollaboratorsModule": {
                    "leadSponsor": {"name": "Philipp Homan"},
                },
                "conditionsModule": {"conditions": ["Psychotic Disorder"]},
                "designModule": {"studyType": "OBSERVATIONAL"},
            },
        },
        {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT00000000",
                    "briefTitle": "",  # missing title -> skipped
                },
            },
        },
    ],
}


def _provider() -> ClinicalTrialsProvider:
    return ClinicalTrialsProvider()


def test_parse_basic() -> None:
    result = _provider()._parse(_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Ga-68-CXCR4 PET/CT in Indolent B-cell Lymphoma"
    assert r.url == "https://clinicaltrials.gov/study/NCT06461182"
    assert r.provider == "clinicaltrials"
    assert r.source == "clinicaltrials.gov"
    assert r.rank == 1
    assert r.published_date == "2027-04"
    assert "RECRUITING" in r.snippet
    assert "Indolent B-Cell Non-Hodgkin Lymphoma" in r.snippet
    assert r.extra["nct_id"] == "NCT06461182"
    assert r.extra["overall_status"] == "RECRUITING"
    assert r.extra["sponsor"] == "Koo Foundation Sun Yat-Sen Cancer Center"
    assert r.extra["study_type"] == "INTERVENTIONAL"
    assert r.extra["primary_completion_date"] == "2027-04"


def test_parse_active_statuses_rank_first() -> None:
    result = _provider()._parse(_RESPONSE)

    # RECRUITING study is ranked before the COMPLETED one.
    assert result.results[0].extra["overall_status"] == "RECRUITING"
    assert result.results[1].extra["overall_status"] == "COMPLETED"
    assert [r.rank for r in result.results] == [1, 2]


def test_parse_limit() -> None:
    result = _provider()._parse(_RESPONSE, max_results=1)
    assert len(result.results) == 1
    assert result.results[0].extra["overall_status"] == "RECRUITING"


def test_parse_empty() -> None:
    result = _provider()._parse({})
    assert result.results == []


def test_parse_malformed_items() -> None:
    data = {"studies": ["not-a-dict", None, 42, {}]}
    result = _provider()._parse(data)
    assert result.results == []


def test_date_or_empty_handles_dict_string_and_none() -> None:
    assert (
        ClinicalTrialsProvider._date_or_empty({"date": "2026-04", "type": "ACTUAL"})
        == "2026-04"
    )
    assert ClinicalTrialsProvider._date_or_empty("2029-01-31") == "2029-01-31"
    assert ClinicalTrialsProvider._date_or_empty(None) == ""
    assert ClinicalTrialsProvider._date_or_empty("") == ""


def test_recruitment_rank() -> None:
    assert ClinicalTrialsProvider._recruitment_rank("RECRUITING") == 0
    assert ClinicalTrialsProvider._recruitment_rank("ACTIVE_NOT_RECRUITING") == 0
    assert ClinicalTrialsProvider._recruitment_rank("NOT_YET_RECRUITING") == 0
    assert ClinicalTrialsProvider._recruitment_rank("COMPLETED") == 1
    assert ClinicalTrialsProvider._recruitment_rank("TERMINATED") == 1
    assert ClinicalTrialsProvider._recruitment_rank("") == 1


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_endpoint(respx_mock) -> None:
    import respx

    respx_mock.get(
        "https://clinicaltrials.gov/api/v2/studies",
        params={
            "query.term": "python",
            "format": "json",
            "pageSize": 5,
        },
    ).mock(
        return_value=respx.MockResponse(200, json=_RESPONSE),
    )

    p = _provider()
    result = await p.search("python", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "clinicaltrials"
    assert result.results[0].url.startswith("https://clinicaltrials.gov/study/")
