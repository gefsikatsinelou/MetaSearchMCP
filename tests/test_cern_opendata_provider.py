"""Unit tests for the CERN Open Data (opendata.cern.ch) provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.cern_opendata import (
    CernOpenDataProvider,
    _abstract,
    _authors,
    _date,
    _formats,
    _license,
    _text,
    _type_label,
)

_SEARCH_URL = "https://opendata.cern.ch/api/records"

_PAYLOAD = {
    "hits": {
        "total": 5566,
        "hits": [
            {
                "id": 300,
                "created": "2016-01-01T00:00:00+00:00",
                "updated": "2020-01-01T00:00:00+00:00",
                "metadata": {
                    "recid": "300",
                    "title": (
                        "Higgs candidate events for use in education and outreach"
                    ),
                    "abstract": {
                        "description": (
                            "<p>This document contains <b>Higgs</b> candidate "
                            "events released by CMS for education.</p>"
                        )
                    },
                    "authors": [
                        {"name": "McCauley, Thomas", "orcid": "0000-0001-6589-8286"},
                        {"name": "Doe, Jane"},
                    ],
                    "keywords": ["education", "education", "higgs"],
                    "experiment": ["CMS"],
                    "type": {"primary": "Dataset", "secondary": ["Derived"]},
                    "doi": "10.7483/OPENDATA.CMS.N9MJ.QEEC",
                    "date_published": "2014",
                    "date_created": ["2011", "2012"],
                    "distribution": {"formats": ["csv", "ig", "csv", "json"]},
                    "availability": "online",
                    "collections": ["CMS-Derived-Datasets"],
                    "license": {"attribution": "CC0-1.0"},
                    "publisher": "CERN Open Data Portal",
                },
            },
            {
                # No published date -> published_date stays None; a full date and
                # a bundled title mapping are exercised here.
                "id": 555,
                "metadata": {
                    "recid": "555",
                    "title": {"title": "Simulated event sample"},
                    "abstract": "Plain text abstract without markup.",
                    "authors": [],
                    "keywords": [],
                    "experiment": ["ATLAS", "ALICE"],
                    "type": {"primary": "Dataset"},
                    "date_published": "2015-07-10",
                    "date_created": ["2010"],
                    "distribution": {"formats": ["json"]},
                    "availability": "partial",
                    "collections": ["ATLAS-Derived-Datasets", "CERN-Open-Data"],
                    "license": {"name": "CC-BY-4.0"},
                },
            },
            {
                # Missing metadata -> skipped.
                "id": 999,
            },
            {
                "id": 1000,
                "metadata": {
                    "recid": "1000",
                    # Missing title -> skipped.
                    "abstract": "orphan",
                },
            },
        ],
    },
}

_EMPTY_PAYLOAD = {"hits": {"total": 0, "hits": []}}


def test_cern_opendata_parse_basic():
    result = CernOpenDataProvider()._parse(_PAYLOAD, 50)

    assert len(result) == 2
    first = result[0]
    assert first.title == "Higgs candidate events for use in education and outreach"
    assert first.url == "https://opendata.cern.ch/record/300"
    assert first.source == "opendata.cern.ch"
    assert first.provider == "cern_opendata"
    assert first.rank == 1
    # HTML is stripped from the abstract.
    assert "Higgs candidate events released by CMS" in first.snippet
    assert "<b>" not in first.snippet
    assert "Authors: McCauley, Thomas, Doe, Jane" in first.snippet
    assert "Keywords: education, higgs" in first.snippet
    assert "Experiment: CMS" in first.snippet
    assert "Type: Dataset" in first.snippet
    assert "Formats: csv, ig, json" in first.snippet
    assert "Availability: online" in first.snippet
    assert "License: CC0-1.0" in first.snippet
    assert first.published_date == "2014"
    assert first.extra["doi"] == "10.7483/OPENDATA.CMS.N9MJ.QEEC"
    assert first.extra["type"] == "Dataset"
    assert first.extra["type_facets"] == ["Derived"]
    assert first.extra["authors"] == ["McCauley, Thomas", "Doe, Jane"]
    assert first.extra["keywords"] == ["education", "higgs"]
    assert first.extra["experiment"] == ["CMS"]
    assert first.extra["formats"] == ["csv", "ig", "json"]
    assert first.extra["availability"] == "online"
    assert first.extra["license"] == "CC0-1.0"
    assert first.extra["publisher"] == "CERN Open Data Portal"
    assert first.extra["created"] == ["2011", "2012"]


def test_cern_opendata_parse_second_record():
    result = CernOpenDataProvider()._parse(_PAYLOAD, 50)

    second = result[1]
    assert second.title == "Simulated event sample"
    assert second.url == "https://opendata.cern.ch/record/555"
    assert second.rank == 2
    assert second.published_date == "2015-07-10"
    assert second.extra["authors"] == []
    assert second.extra["experiment"] == ["ATLAS", "ALICE"]
    assert second.extra["license"] == "CC-BY-4.0"
    assert second.extra["type_facets"] == []


def test_cern_opendata_parse_skips_incomplete_items():
    result = CernOpenDataProvider()._parse(_PAYLOAD, 50)
    urls = [r.url for r in result]
    assert "https://opendata.cern.ch/record/999" not in urls
    assert "https://opendata.cern.ch/record/1000" not in urls
    assert all(r.title != "orphan" for r in result)


def test_cern_opendata_parse_respects_limit():
    result = CernOpenDataProvider()._parse(_PAYLOAD, 1)
    assert len(result) == 1
    assert result[0].rank == 1


def test_cern_opendata_parse_dedupes_by_recid():
    payload = {"hits": {"hits": [_PAYLOAD["hits"]["hits"][0]] * 2}}
    result = CernOpenDataProvider()._parse(payload, 50)
    assert len(result) == 1


def test_cern_opendata_parse_empty_and_malformed():
    provider = CernOpenDataProvider()
    assert provider._parse(_EMPTY_PAYLOAD, 50) == []
    assert provider._parse({}, 50) == []
    assert provider._parse({"hits": None}, 50) == []
    assert provider._parse({"hits": {"hits": None}}, 50) == []
    assert provider._parse([], 50) == []


def test_cern_opendata_text_helper():
    assert _text("hello   world") == "hello world"
    assert _text({"title": "Mapped"}) == "Mapped"
    assert _text({"value": "Val"}) == "Val"
    assert _text([{"title": "First"}, "Second"]) == "First"
    assert _text(["", "   ", "Third"]) == "Third"
    assert _text(None) == ""
    assert _text([]) == ""


def test_cern_opendata_abstract_helper():
    assert _abstract({"abstract": {"description": "<p>Hi <b>x</b></p>"}}) == "Hi x"
    assert _abstract({"abstract": "plain"}) == "plain"
    assert _abstract({}) == ""


def test_cern_opendata_authors_helper():
    value = [
        {"name": "One"},
        {"name": "One"},
        {"name": "Two"},
        "bare",
        {"nope": "x"},
    ]
    assert _authors(value, 5) == ["One", "Two", "bare"]
    assert _authors(value, 1) == ["One"]
    assert _authors(None, 5) == []


def test_cern_opendata_formats_and_type_helpers():
    assert _formats({"formats": ["csv", "csv", "json"]}, 4) == ["csv", "json"]
    assert _formats({"formats": None}, 4) == []
    assert _formats(None, 4) == []
    assert _type_label({"primary": "Dataset", "secondary": ["Derived"]}) == "Dataset"
    assert _type_label("Dataset") == "Dataset"
    assert _type_label(None) == ""


def test_cern_opendata_license_and_date_helpers():
    assert _license({"attribution": "CC0-1.0"}) == "CC0-1.0"
    assert _license({"name": "CC-BY-4.0"}) == "CC-BY-4.0"
    assert _license("MIT") == "MIT"
    assert _license(None) == ""
    assert _date("2014") == "2014"
    assert _date("2015-07-10") == "2015-07-10"
    assert _date(None) is None
    assert _date("") is None


def test_cern_opendata_is_available_and_registered():
    provider = CernOpenDataProvider()
    assert provider.is_available() is True
    assert provider.name == "cern_opendata"
    assert {"academic", "data", "science", "physics"}.issubset(set(provider.tags))

    from metasearchmcp.catalog import build_provider_catalog

    catalog = build_provider_catalog()
    assert "cern_opendata" in catalog


@pytest.mark.asyncio
async def test_cern_opendata_search_builds_query(respx_mock):
    respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=_PAYLOAD),
    )

    provider = CernOpenDataProvider()
    result = await provider.search("higgs", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "cern_opendata"
    request = respx_mock.calls.last.request
    assert request.url.params["q"] == "higgs"
    assert request.url.params["size"] == "5"
    assert request.url.params["page"] == "1"


@pytest.mark.asyncio
async def test_cern_opendata_search_blank_query_skips_request(respx_mock):
    provider = CernOpenDataProvider()
    result = await provider.search("   ", SearchParams(num_results=5))
    assert result.results == []
    assert respx_mock.calls.call_count == 0


@pytest.mark.asyncio
async def test_cern_opendata_search_raises_on_error(respx_mock):
    respx_mock.get(_SEARCH_URL).mock(return_value=respx.MockResponse(500))

    provider = CernOpenDataProvider()
    with pytest.raises(HTTPStatusError):
        await provider.search("higgs", SearchParams(num_results=5))
