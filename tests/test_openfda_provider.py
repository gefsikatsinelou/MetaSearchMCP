"""Unit tests for the openFDA drug approval search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.openfda import OpenFDADrugProvider

_SAMPLE_ITEM = {
    "application_number": "NDA020748",
    "sponsor_name": "PFIZER",
    "products": [
        {
            "brand_name": "CELEBREX",
            "active_ingredients": [{"name": "CELECOXIB", "strength": "100MG"}],
            "dosage_form": "CAPSULE",
            "route": "ORAL",
            "marketing_status": "Prescription",
        },
    ],
    "submissions": [
        {
            "submission_type": "ORIG",
            "submission_status": "AP",
            "submission_status_date": "19981231",
        },
    ],
}

_SAMPLE_RESPONSE: dict[str, object] = {
    "meta": {"results": {"skip": 0, "limit": 3, "total": 2}},
    "results": [
        _SAMPLE_ITEM,
        {
            # No products -> skipped.
            "application_number": "NDA000001",
            "sponsor_name": "PHARMA",
        },
        {
            "application_number": "ANDA075000",
            "sponsor_name": "TEVA",
            "products": [
                {
                    "brand_name": "",
                    "active_ingredients": [
                        {"name": "ACETAMINOPHEN", "strength": "500MG"}
                    ],
                    "dosage_form": "TABLET",
                    "route": "ORAL",
                    "marketing_status": "Discontinued",
                },
            ],
            "submissions": [
                {
                    "submission_type": "SUPPL",
                    "submission_status": "AP",
                    "submission_status_date": "20010415",
                },
            ],
        },
        "not-a-dict",
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"results": []}


def _provider() -> OpenFDADrugProvider:
    return OpenFDADrugProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "openfda"
    assert p.tags == ["drugs", "pharma", "medical", "bio", "web"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "CELEBREX"
    assert r.url == (
        "https://www.accessdata.fda.gov/scripts/cder/daf/"
        "index.cfm?event=overview.process&ApplNo=NDA020748"
    )
    assert "PFIZER" in r.snippet
    assert "Active: CELECOXIB 100MG" in r.snippet
    assert "CAPSULE" in r.snippet
    assert "ORAL" in r.snippet
    assert "Approved: 1998-12-31" in r.snippet
    assert r.provider == "openfda"
    assert r.source == "open.fda.gov"
    assert r.rank == 1
    assert r.published_date == "1998-12-31"
    assert r.extra["application_number"] == "NDA020748"
    assert r.extra["sponsor"] == "PFIZER"
    assert r.extra["active_ingredients"] == ["CELECOXIB 100MG"]
    assert r.extra["dosage_form"] == "CAPSULE"
    assert r.extra["route"] == "ORAL"
    assert r.extra["marketing_status"] == "Prescription"
    assert r.extra["submission_type"] == "ORIG"
    assert r.extra["submission_status"] == "AP"


def test_parse_fallback_title_from_ingredients() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    r = result.results[1]
    assert r.title == "ACETAMINOPHEN"
    assert r.rank == 2
    assert r.published_date == "2001-04-15"
    assert r.extra["marketing_status"] == "Discontinued"


def test_parse_skips_items_without_products() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert all(r.title and r.extra["application_number"] for r in result.results)


def test_parse_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1
    assert result.results[0].title == "CELEBREX"


def test_parse_empty_and_malformed() -> None:
    assert _provider()._parse(_EMPTY_RESPONSE).results == []
    assert _provider()._parse({}).results == []
    assert _provider()._parse({"results": None}).results == []
    assert _provider()._parse({"results": "junk"}).results == []
    assert _provider()._parse(None).results == []
    assert _provider()._parse([]).results == []


def test_submission_summary_guards_against_junk() -> None:
    assert OpenFDADrugProvider._submission_summary(None) == {}
    assert OpenFDADrugProvider._submission_summary("junk") == {}
    # Only approved submissions are summarized.
    assert (
        OpenFDADrugProvider._submission_summary(
            [{"submission_status": "REJ", "submission_status_date": "20200101"}]
        )
        == {}
    )
    summary = OpenFDADrugProvider._submission_summary(
        [
            {
                "submission_type": "ORIG",
                "submission_status": "AP",
                "submission_status_date": "19981231",
            },
        ]
    )
    assert summary["submission_date"] == "1998-12-31"


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.fda.gov/drug/drugsfda.json").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("celebrex", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "openfda"
    request = respx_mock.calls.last.request
    assert request.url.params["search"] == "celebrex"
    assert request.url.params["limit"] == "5"


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.fda.gov/drug/drugsfda.json").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("zzzz", SearchParams(num_results=5))
    assert result.results == []
