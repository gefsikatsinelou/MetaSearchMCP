"""Unit tests for the Harvard Dataverse dataset search provider."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.harvard_dataverse import HarvardDataverseProvider

_ENDPOINT = "https://dataverse.harvard.edu/api/search"

_DATASET: dict[str, Any] = {
    "name": "Replication Data for: Polarization and Turnout in Brazil",
    "type": "dataset",
    "url": "https://doi.org/10.7910/DVN/ABCDEF",
    "global_id": "doi:10.7910/DVN/ABCDEF",
    "description": "Replication files for the study of polarization and turnout.",
    "published_at": "2021-03-04T10:09:08Z",
    "publisher": "Polarization Dataverse",
    "identifier_of_dataverse": "polar",
    "name_of_dataverse": "Polarization Dataverse",
    "subjects": ["Social Sciences", "Political Science"],
    "fileCount": 12,
    "versionId": 500,
    "versionState": "RELEASED",
    "majorVersion": 2,
    "minorVersion": 1,
    "createdAt": "2021-03-04T09:00:00Z",
    "updatedAt": "2021-03-05T09:00:00Z",
    "publicationStatuses": ["Published"],
    "contacts": [{"name": "Silva, Ana", "affiliation": "University of Brasilia"}],
    "authors": ["Silva, Ana", "Costa, Bruno", "Nunes, Carla", "Pereira, Daniel"],
}

# Minimal record: only a title and an identifier that is not a DOI.
_BARE: dict[str, Any] = {
    "name": "Bare Dataset",
    "global_id": "hdl:1902.1/12345",
}

# Hand-written record with unusual field types and embedded HTML.
_ODD: dict[str, Any] = {
    "name": "  Odd   dataset  ",
    "type": "dataset",
    "url": "",
    "global_id": "doi:10.7910/DVN/ODD001",
    "description": "<p>Data &amp; <b>code</b>\nfor the study</p>",
    "subjects": "Social Sciences",
    "authors": [1, "One, A", ""],
    "fileCount": True,
    "majorVersion": "2",
    "minorVersion": 3,
    "contacts": ["nope", {"affiliation": "Nowhere"}, {"name": " Doe, J "}],
}


def _envelope(items: list[Any], total: object = 1234) -> dict[str, Any]:
    """Wrap *items* in a successful Dataverse search response envelope."""
    return {
        "status": "OK",
        "data": {"q": "x", "total_count": total, "start": 0, "items": items},
    }


def test_harvard_dataverse_name_tags_and_availability() -> None:
    p = HarvardDataverseProvider()
    assert p.name == "harvard_dataverse"
    assert p.tags == ["academic", "data", "datasets", "repositories"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_harvard_dataverse_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "harvard_dataverse" in registry
    assert registry["harvard_dataverse"].tags == [
        "academic",
        "data",
        "datasets",
        "repositories",
    ]


def test_harvard_dataverse_parse_dataset_record() -> None:
    p = HarvardDataverseProvider()
    result = p._parse(_envelope([_DATASET]), limit=5)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Replication Data for: Polarization and Turnout in Brazil"
    assert r.url == "https://doi.org/10.7910/DVN/ABCDEF"
    assert r.source == "dataverse.harvard.edu"
    assert r.provider == "harvard_dataverse"
    assert r.rank == 1
    assert r.published_date == "2021-03-04"
    assert r.snippet == (
        "Silva, Ana, Costa, Bruno, Nunes, Carla et al. | 2021-03-04 | "
        "Polarization Dataverse | Social Sciences, Political Science | 12 files"
    )
    assert r.extra["doi"] == "10.7910/DVN/ABCDEF"
    assert r.extra["global_id"] == "doi:10.7910/DVN/ABCDEF"
    assert r.extra["authors"] == [
        "Silva, Ana",
        "Costa, Bruno",
        "Nunes, Carla",
        "Pereira, Daniel",
    ]
    assert r.extra["publisher"] == "Polarization Dataverse"
    assert r.extra["dataverse"] == "Polarization Dataverse"
    assert r.extra["dataverse_alias"] == "polar"
    assert r.extra["subjects"] == ["Social Sciences", "Political Science"]
    assert r.extra["file_count"] == 12
    assert r.extra["version"] == "2.1"
    assert r.extra["version_state"] == "RELEASED"
    assert r.extra["publication_statuses"] == ["Published"]
    assert r.extra["contacts"] == [
        {"name": "Silva, Ana", "affiliation": "University of Brasilia"}
    ]
    assert r.extra["created_at"] == "2021-03-04T09:00:00Z"
    assert r.extra["updated_at"] == "2021-03-05T09:00:00Z"
    assert r.extra["total_results"] == 1234


def test_harvard_dataverse_bare_record_falls_back_to_home_page() -> None:
    p = HarvardDataverseProvider()
    r = p._parse(_envelope([_BARE], total=None)).results[0]

    assert r.title == "Bare Dataset"
    # No landing URL and no DOI, so the repository home page is used.
    assert r.url == "https://dataverse.harvard.edu/"
    # The snippet falls back to the record's global identifier.
    assert r.snippet == "hdl:1902.1/12345"
    assert r.extra["doi"] == "hdl:1902.1/12345"
    assert r.extra["authors"] == []
    assert r.extra["subjects"] == []
    assert r.extra["file_count"] is None
    assert r.extra["version"] is None
    assert r.extra["total_results"] is None


def test_harvard_dataverse_doi_url_fallback_without_landing_url() -> None:
    p = HarvardDataverseProvider()
    record = {"name": "No URL", "url": "", "global_id": "doi:10.7910/DVN/XYZ"}
    r = p._parse(_envelope([record])).results[0]

    assert r.url == "https://doi.org/10.7910/DVN/XYZ"
    assert r.extra["doi"] == "10.7910/DVN/XYZ"


def test_harvard_dataverse_parse_odd_field_types() -> None:
    p = HarvardDataverseProvider()
    r = p._parse(_envelope([_ODD])).results[0]

    assert r.title == "Odd dataset"
    assert r.url == "https://doi.org/10.7910/DVN/ODD001"
    assert r.snippet == "One, A"
    # Absent fields are simply left out of the snippet.
    assert r.published_date is None
    assert r.extra["authors"] == ["One, A"]
    assert r.extra["subjects"] == []
    assert r.extra["file_count"] is None
    assert r.extra["version"] is None
    assert r.extra["contacts"] == [{"name": "Doe, J"}]
    assert r.extra["description"] == "Data & code for the study"


def test_harvard_dataverse_parse_skips_records_without_name() -> None:
    p = HarvardDataverseProvider()
    payload = _envelope([{}, {"type": "dataset"}, "nope", _BARE])
    results = p._parse(payload).results

    assert [r.title for r in results] == ["Bare Dataset"]
    assert results[0].rank == 1


def test_harvard_dataverse_parse_respects_limit() -> None:
    p = HarvardDataverseProvider()
    items = [dict(_BARE, name=f"dataset{n}") for n in range(3)]

    assert len(p._parse(_envelope(items), limit=2).results) == 2
    assert len(p._parse(_envelope(items)).results) == 3


def test_harvard_dataverse_parse_empty_and_malformed() -> None:
    p = HarvardDataverseProvider()
    assert p._parse(_envelope([])).results == []
    assert p._parse({}).results == []
    assert p._parse({"status": "ERROR", "message": "boom"}).results == []
    assert p._parse({"status": "OK"}).results == []
    assert p._parse({"status": "OK", "data": {}}).results == []
    assert p._parse({"status": "OK", "data": {"items": "nope"}}).results == []
    assert p._parse({"status": "OK", "data": {"items": [1, 2, 3]}}).results == []
    unnamed = {"status": "OK", "data": {"items": [{"type": "dataset"}]}}
    assert p._parse(unnamed).results == []
    assert p._parse([1, 2, 3]).results == []
    assert p._parse(None).results == []


def test_harvard_dataverse_helpers() -> None:
    from metasearchmcp.providers.harvard_dataverse import (
        _clean,
        _contacts,
        _int,
        _strings,
        _text,
    )

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _clean(5) == ""

    assert _text("<p>A &amp; <b>B</b></p>") == "A & B"
    assert _text("  ") == ""
    assert _text(None) == ""

    assert _int(3) == 3
    assert _int(True) is None
    assert _int("3") is None
    assert _int(None) is None

    assert _strings([" a ", "", 5, None]) == ["a"]
    assert _strings("a") == []
    assert _strings(None) == []

    assert _contacts([{"name": " a ", "affiliation": " b "}, {"name": ""}, 5]) == [
        {"name": "a", "affiliation": "b"}
    ]
    assert _contacts(None) == []


def test_harvard_dataverse_version_label() -> None:
    p = HarvardDataverseProvider()

    assert p._version({"majorVersion": 3, "minorVersion": 0}) == "3.0"
    assert p._version({"majorVersion": 3}) == "3.0"
    assert p._version({}) == ""


async def test_harvard_dataverse_search_sends_expected_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope([_DATASET, _BARE]))
    )

    result = await HarvardDataverseProvider().search(
        "  polarization  ",
        SearchParams(num_results=7),
    )

    assert route.called
    params = route.calls[0].request.url.params
    assert params["q"] == "polarization"
    assert params["type"] == "dataset"
    assert params["per_page"] == "7"
    assert params["start"] == "0"
    assert len(respx_mock.calls) == 1
    assert [r.title for r in result.results] == [
        "Replication Data for: Polarization and Turnout in Brazil",
        "Bare Dataset",
    ]


async def test_harvard_dataverse_search_caps_results_to_provider_limit(
    respx_mock,
) -> None:
    respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(
            200,
            json=_envelope([dict(_BARE, name=f"dataset{n}") for n in range(10)]),
        )
    )

    provider = HarvardDataverseProvider()
    provider._max_results = 3
    result = await provider.search("data", SearchParams(num_results=50))

    assert len(respx_mock.calls) == 1
    assert len(result.results) == 3
    assert respx_mock.calls[0].request.url.params["per_page"] == "3"


async def test_harvard_dataverse_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT)

    result = await HarvardDataverseProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_harvard_dataverse_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(503))

    with pytest.raises(httpx.HTTPStatusError):
        await HarvardDataverseProvider().search("data", SearchParams())
