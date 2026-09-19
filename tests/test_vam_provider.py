"""Unit tests for the Victoria and Albert Museum (V&A) collection provider."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.vam import VamProvider

_ENDPOINT = "https://api.vam.ac.uk/v2/objects/search"

_CHAIR: dict[str, Any] = {
    "systemNumber": "O72610",
    "accessionNumber": "W.2-1995",
    "objectType": "Chair",
    "availableToBook": True,
    "_currentLocation": {
        "id": "THES343731",
        "displayName": "In Store",
        "type": "storage",
        "site": "ES",
        "onDisplay": False,
        "detail": {"free": "", "case": "", "shelf": "", "box": ""},
    },
    "_primaryTitle": "Ply Chair",
    "_primaryMaker": {"name": "Morrison, Jasper", "association": "designer"},
    "_primaryImageId": "2006AU1797",
    "_primaryDate": "1990",
    "_primaryPlace": "Great Britain",
    "_warningTypes": ["Textile requires appointment"],
    "_images": {
        "_primary_thumbnail": (
            "https://framemark.vam.ac.uk/collections/2006AU1797/full/!100,100/0/default.jpg"
        ),
        "_iiif_image_base_url": "https://framemark.vam.ac.uk/collections/2006AU1797/",
        "_iiif_presentation_url": None,
        "imageResolution": "low",
    },
}

# A minimal record: no title, maker, date, place, location or images.
_SPARSE: dict[str, Any] = {
    "systemNumber": "O1",
    "accessionNumber": "CIRC.1-1900",
    "objectType": "Teapot",
    "availableToBook": False,
    "_currentLocation": None,
    "_images": None,
}

_ON_DISPLAY: dict[str, Any] = {
    "systemNumber": "O186718",
    "accessionNumber": "CIRC.34A-1976",
    "objectType": "Teapot and cover",
    "_primaryMaker": {"name": "Unknown", "association": ""},
    "_currentLocation": {
        "displayName": "Ceramics, Room 143, The Timothy Sainsbury Gallery",
        "site": "VA",
        "onDisplay": True,
    },
    "_images": {
        "_primary_thumbnail": "https://framemark.vam.ac.uk/x/full/!100,100/0/default.jpg",
    },
}


def _envelope(
    records: list[Any],
    total: object = 13827,
    image_count: int = 20864,
) -> dict[str, Any]:
    """Wrap *records* in a V&A search response envelope."""
    return {
        "info": {
            "version": "2.0",
            "record_count": total,
            "record_count_exact": True,
            "page_size": 10,
            "pages": 1383,
            "page": 1,
            "image_count": image_count,
        },
        "records": records,
        "clusters": {},
    }


def test_vam_name_tags_and_availability() -> None:
    p = VamProvider()
    assert p.name == "vam"
    assert p.tags == ["art", "images", "media"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_vam_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "vam" in registry
    assert registry["vam"].tags == ["art", "images", "media"]


def test_vam_parse_full_record() -> None:
    p = VamProvider()
    result = p._parse(_envelope([_CHAIR]), limit=5)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Ply Chair"
    assert r.url == "https://collections.vam.ac.uk/item/O72610/"
    assert r.source == "collections.vam.ac.uk"
    assert r.provider == "vam"
    assert r.rank == 1
    assert r.published_date is None
    assert r.snippet == (
        "Chair | by Morrison, Jasper (designer) | 1990 | Great Britain | "
        "Location: In Store | image available"
    )
    assert r.extra["system_number"] == "O72610"
    assert r.extra["accession_number"] == "W.2-1995"
    assert r.extra["object_type"] == "Chair"
    assert r.extra["maker"] == "Morrison, Jasper"
    assert r.extra["maker_association"] == "designer"
    assert r.extra["date"] == "1990"
    assert r.extra["place"] == "Great Britain"
    assert r.extra["on_display"] is False
    assert r.extra["location"] == "In Store"
    assert r.extra["site"] == "ES"
    assert r.extra["image_id"] == "2006AU1797"
    assert r.extra["image_resolution"] == "low"
    assert r.extra["available_to_book"] is True
    assert r.extra["warnings"] == ["Textile requires appointment"]
    assert r.extra["item_url"] == "https://collections.vam.ac.uk/item/O72610/"
    assert r.extra["total_results"] == 13827
    assert r.extra["image_url"] == (
        "https://framemark.vam.ac.uk/collections/2006AU1797/"
    )
    assert r.extra["thumbnail_url"].endswith("/full/!100,100/0/default.jpg")


def test_vam_parse_sparse_record() -> None:
    p = VamProvider()
    r = p._parse(_envelope([_SPARSE], total=None)).results[0]

    assert r.title == "Teapot"
    assert r.url == "https://collections.vam.ac.uk/item/O1/"
    assert r.snippet == "Teapot"
    assert r.extra["maker"] is None
    assert r.extra["maker_association"] is None
    assert r.extra["date"] is None
    assert r.extra["place"] is None
    assert r.extra["location"] is None
    assert r.extra["site"] is None
    assert r.extra["on_display"] is False
    assert r.extra["image_id"] is None
    assert r.extra["thumbnail_url"] is None
    assert r.extra["image_url"] is None
    assert r.extra["warnings"] == []
    assert r.extra["available_to_book"] is False
    assert r.extra["total_results"] is None


def test_vam_parse_on_display_record() -> None:
    p = VamProvider()
    r = p._parse(_envelope([_ON_DISPLAY])).results[0]

    assert r.title == "Teapot and cover"
    assert r.snippet == (
        "Teapot and cover | by Unknown | "
        "On display: Ceramics, Room 143, The Timothy Sainsbury Gallery | "
        "image available"
    )
    assert r.extra["on_display"] is True
    assert r.extra["site"] == "VA"
    assert r.extra["image_url"] is None
    assert r.extra["thumbnail_url"].startswith("https://framemark.vam.ac.uk/")


def test_vam_title_falls_back_to_accession_number() -> None:
    p = VamProvider()
    r = p._parse(_envelope([{"systemNumber": "O2", "accessionNumber": "M.21-2025"}]))
    assert r.results[0].title == "M.21-2025"


def test_vam_parse_skips_records_without_identifier_or_title() -> None:
    p = VamProvider()
    payload = _envelope([{}, {"systemNumber": "O3"}, {"accessionNumber": "X"}, "nope"])

    assert p._parse(payload).results == []


def test_vam_parse_respects_limit_and_ranks() -> None:
    p = VamProvider()
    records = [dict(_SPARSE, systemNumber=f"O{n}") for n in (1, 2, 3)]
    payload = _envelope(records)

    assert len(p._parse(payload, limit=2).results) == 2
    assert [r.rank for r in p._parse(payload, limit=2).results] == [1, 2]
    assert len(p._parse(payload).results) == 3


def test_vam_parse_empty_and_malformed() -> None:
    p = VamProvider()
    assert p._parse(_envelope([])).results == []
    assert p._parse({}).results == []
    assert p._parse({"info": "nope", "records": []}).results == []
    assert p._parse({"records": "nope"}).results == []
    assert p._parse({"records": [1, 2, 3]}).results == []
    assert p._parse([1, 2, 3]).results == []
    assert p._parse(None).results == []


def test_vam_parse_ignores_odd_field_types() -> None:
    p = VamProvider()
    payload = _envelope(
        [
            {"systemNumber": 5, "objectType": "Chair"},
            {
                "systemNumber": "O4",
                "objectType": "  Odd   object ",
                "_primaryTitle": None,
                "_primaryMaker": "nope",
                "_currentLocation": "nope",
                "_images": "nope",
                "_warningTypes": ["", 5, "  fragile  "],
                "availableToBook": "yes",
            },
        ],
        total="many",
    )
    r = p._parse(payload).results[0]

    assert len(p._parse(payload).results) == 1
    assert r.title == "Odd object"
    assert r.snippet == "Odd object"
    assert r.extra["maker"] is None
    assert r.extra["location"] is None
    assert r.extra["warnings"] == ["fragile"]
    assert r.extra["available_to_book"] is True
    assert r.extra["total_results"] is None


def test_vam_helpers() -> None:
    from metasearchmcp.providers.vam import (
        _clean,
        _images,
        _int,
        _location,
        _maker,
        _total_results,
        _warnings,
    )

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _clean(5) == ""
    assert _int(12) == 12
    assert _int(True) is None
    assert _int("12") is None

    assert _maker({"_primaryMaker": {"name": "Pugin", "association": "designer"}}) == (
        "Pugin",
        "designer",
    )
    assert _maker({"_primaryMaker": "nope"}) == ("", "")
    assert _maker({}) == ("", "")
    assert _maker("nope") == ("", "")

    assert _images({"_images": {"_primaryImageId": "x"}}) == {"_primaryImageId": "x"}
    assert _images("nope") == {}

    assert _location(
        {"_currentLocation": {"displayName": "Room 1", "site": "VA", "onDisplay": True}}
    ) == ("Room 1", "VA", True)
    assert _location(None) == ("", "", False)
    assert _location({"_currentLocation": "nope"}) == ("", "", False)

    assert _warnings({"_warningTypes": ["a", "", 3]}) == ["a"]
    assert _warnings("nope") == []

    assert _total_results({"info": {"record_count": 5}}) == 5
    assert _total_results({"info": {}}) is None
    assert _total_results({"info": "nope"}) is None
    assert _total_results({}) is None
    assert _total_results(None) is None


async def test_vam_search_sends_expected_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope([_CHAIR, _SPARSE]))
    )

    result = await VamProvider().search("chair", SearchParams(num_results=5))

    assert route.called
    params = route.calls[0].request.url.params
    assert params["q"] == "chair"
    assert params["page_size"] == "5"
    assert params["page"] == "1"
    assert len(respx_mock.calls) == 1
    assert [r.extra["system_number"] for r in result.results] == ["O72610", "O1"]


async def test_vam_search_caps_results_to_provider_limit(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(
            200,
            json=_envelope([dict(_SPARSE, systemNumber=f"O{n}") for n in range(1, 6)]),
        )
    )

    provider = VamProvider()
    provider._max_results = 2
    result = await provider.search("teapot", SearchParams(num_results=50))

    assert respx_mock.calls[0].request.url.params["page_size"] == "2"
    assert len(result.results) == 2


async def test_vam_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT)

    result = await VamProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_vam_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(503))

    with pytest.raises(httpx.HTTPStatusError):
        await VamProvider().search("chair", SearchParams())
