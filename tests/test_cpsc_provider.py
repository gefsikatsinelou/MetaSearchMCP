"""Unit tests for the keyless CPSC consumer product recall search provider."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.cpsc import CpscProvider

_ENDPOINT = "https://www.saferproducts.gov/RestWebServices/Recall"

_BIB: dict[str, Any] = {
    "RecallID": 10880,
    "RecallNumber": "26639",
    "RecallDate": "2026-07-23T00:00:00",
    "Description": (
        "This recall involves Peony Design personalized handmade baby bibs "
        "and stroller bags."
    ),
    "URL": (
        "https://www.cpsc.gov/Recalls/2026/"
        "Peony-Design-Recalls-Baby-Bibs-and-Stroller-Bags"
    ),
    "Title": (
        "Peony Design Recalls Personalized Baby Bibs and Stroller Bags "
        "Due to Choking Hazard"
    ),
    "ConsumerContact": "Peony Design by email at peony@example.com.",
    "LastPublishDate": "2026-07-24T00:00:00",
    "Products": [
        {
            "Name": "Personalized Baby Bibs and Stroller Bags",
            "Type": "Toys",
            "NumberOfUnits": "About 52",
        },
    ],
    "Images": [
        {
            "URL": "https://www.cpsc.gov/s3fs-public/peony-1.png",
            "Caption": "Recalled bib",
        },
    ],
    "Injuries": [],
    "Manufacturers": [],
    "Importers": [{"Name": "Peony Design, of Coshocton, Ohio", "CompanyID": ""}],
    "Hazards": [{"Name": "The bibs pose a choking hazard to young children."}],
    "ManufacturerCountries": [{"Country": "China"}],
}

_LAMINATOR: dict[str, Any] = {
    "RecallID": 11022,
    "RecallNumber": "27024",
    "RecallDate": "2026-10-15T00:00:00",
    "Description": "This recall involves the Scotch thermal laminator.",
    "URL": "",
    "Title": "3M Company Recalls Scotch Thermal Laminators Due to Fire Hazard",
    "Products": [
        {"Name": "Scotch Thermal Laminators", "Type": "Business and Office Machines"},
    ],
    "Hazards": [{"Name": "The laminators can overheat, posing a fire hazard."}],
    "Manufacturers": [{"Name": "3M Company, of St. Paul, Minnesota"}],
}


def test_cpsc_name_tags_and_availability() -> None:
    p = CpscProvider()
    assert p.name == "cpsc"
    assert p.tags == ["products", "gov", "us"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_cpsc_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "cpsc" in registry
    assert registry["cpsc"].tags == ["products", "gov", "us"]


def test_cpsc_parse_single_recall() -> None:
    p = CpscProvider()
    result = p._parse([_BIB], limit=5)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == (
        "Peony Design Recalls Personalized Baby Bibs and Stroller Bags "
        "Due to Choking Hazard"
    )
    assert r.url == (
        "https://www.cpsc.gov/Recalls/2026/"
        "Peony-Design-Recalls-Baby-Bibs-and-Stroller-Bags"
    )
    assert r.source == "saferproducts.gov"
    assert r.provider == "cpsc"
    assert r.rank == 1
    assert r.published_date == "2026-07-23"
    assert r.snippet == (
        "This recall involves Peony Design personalized handmade baby bibs and "
        "stroller bags. | Products: Personalized Baby Bibs and Stroller Bags "
        "(Toys) | Hazard: The bibs pose a choking hazard to young children."
    )
    assert r.extra["recall_number"] == "26639"
    assert r.extra["recall_id"] == 10880
    assert r.extra["products"] == ["Personalized Baby Bibs and Stroller Bags"]
    assert r.extra["category"] == "Toys"
    assert r.extra["units"] == "About 52"
    assert r.extra["hazards"] == ["The bibs pose a choking hazard to young children."]
    assert r.extra["firm"] == "Peony Design, of Coshocton, Ohio"
    assert r.extra["countries"] == ["China"]
    assert r.extra["image"] == "https://www.cpsc.gov/s3fs-public/peony-1.png"


def test_cpsc_parse_falls_back_to_recall_url_without_url() -> None:
    p = CpscProvider()
    r = p._parse([_LAMINATOR]).results[0]

    assert r.url == "https://www.cpsc.gov/Recalls"
    assert r.rank == 1
    assert r.extra["units"] is None
    assert r.extra["firm"] == "3M Company, of St. Paul, Minnesota"
    assert r.extra["category"] == "Business and Office Machines"


def test_cpsc_parse_preserves_order_and_ranks() -> None:
    p = CpscProvider()
    result = p._parse([_BIB, _LAMINATOR])

    assert [r.extra["recall_number"] for r in result.results] == ["26639", "27024"]
    assert [r.rank for r in result.results] == [1, 2]


def test_cpsc_parse_skips_unusable_records() -> None:
    p = CpscProvider()
    payload = [
        {},
        {"Title": ""},
        {"RecallNumber": "1234"},
        {"Title": "  Air fryer recall  ", "RecallNumber": "9999"},
    ]
    results = p._parse(payload).results

    assert [r.title for r in results] == ["CPSC recall 1234", "Air fryer recall"]
    assert [r.rank for r in results] == [1, 2]
    assert results[0].snippet == ""


def test_cpsc_parse_respects_limit() -> None:
    p = CpscProvider()
    payload = [dict(_BIB, RecallNumber=str(n)) for n in range(1, 6)]

    assert len(p._parse(payload, limit=1).results) == 1
    assert len(p._parse(payload).results) == 5


def test_cpsc_parse_empty_and_malformed() -> None:
    p = CpscProvider()
    assert p._parse([]).results == []
    assert p._parse({}).results == []
    assert p._parse("nope").results == []
    assert p._parse(None).results == []
    assert p._parse([_BIB, "nope", 3]).results[0].extra["recall_number"] == "26639"


def test_cpsc_helpers() -> None:
    from metasearchmcp.providers.cpsc import _clean

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _clean(42) == ""
    assert CpscProvider._names([{"Name": "x"}, {"Name": ""}, {}, "y"]) == ["x"]
    assert CpscProvider._names("nope") == []
    assert CpscProvider._countries([{"Country": "China"}, {}]) == ["China"]
    assert CpscProvider._countries(None) == []
    assert CpscProvider._first_url([{"URL": "u"}, {"URL": "v"}]) == "u"
    assert CpscProvider._first_url([{"URL": ""}, {"URL": "v"}]) == "v"
    assert CpscProvider._first_url(None) == ""
    assert (
        CpscProvider._first_product_field(
            [{"Type": "Toys"}],
            "Type",
        )
        == "Toys"
    )
    assert CpscProvider._first_product_field([{}], "Type") == ""


async def test_cpsc_search_sends_expected_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=[_BIB])
    )

    result = await CpscProvider().search("stroller", SearchParams(num_results=5))

    assert route.called
    request = route.calls[0].request
    assert request.url.params["format"] == "json"
    assert request.url.params["ProductName"] == "stroller"
    assert [r.title for r in result.results] == [_BIB["Title"]]


async def test_cpsc_search_no_matches_returns_empty(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(200, json=[]))

    result = await CpscProvider().search("zzz", SearchParams())
    assert result.results == []


async def test_cpsc_search_respects_result_limits(respx_mock) -> None:
    recalls = [dict(_BIB, RecallNumber=str(n)) for n in range(1, 41)]
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(200, json=recalls))

    provider = CpscProvider()
    provider._max_results = 1000
    result = await provider.search("bib", SearchParams(num_results=30))
    assert len(result.results) == 30

    provider._max_results = 1
    result = await provider.search("bib", SearchParams(num_results=30))
    assert len(result.results) == 1


async def test_cpsc_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT)

    result = await CpscProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_cpsc_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(500))

    with pytest.raises(httpx.HTTPStatusError):
        await CpscProvider().search("stroller", SearchParams())
