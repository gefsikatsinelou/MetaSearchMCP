"""Unit tests for the UK government open data catalogue provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.uk_open_data import UkOpenDataProvider

_SEARCH_URL = "https://ckan.publishing.service.gov.uk/api/3/action/package_search"

_PAYLOAD = {
    "success": True,
    "result": {
        "count": 2871,
        "results": [
            {
                "title": "Flooding",
                "name": "flooding2",
                "notes": (
                    "<dp-prose>\n  <p>Details of flood recovery work in the "
                    "Calder valley.</p>\n</dp-prose>"
                ),
                "author": "Calderdale Council",
                "id": "b2cc36a7-33d3-43de-81d5-f7038c34dd1a",
                "organization": {
                    "title": "Calderdale Metropolitan Borough Council",
                    "name": "calderdale-metropolitan-borough-council",
                },
                "url": "https://dataworks.calderdale.gov.uk/dataset/flooding-e50rg",
                "tags": [
                    {"name": "flooding"},
                    {"name": "flooding"},
                    {"name": "environment"},
                ],
                "resources": [
                    {"format": "CSV"},
                    {"format": "GeoJSON"},
                    {"format": "CSV"},
                ],
                "license_title": "UK Open Government Licence (OGL)",
                "isopen": True,
                "num_resources": 7,
                "metadata_modified": "2026-09-25T11:50:26.789461",
            },
            {
                "title": "Bare Dataset",
                "name": "bare-dataset",
                "organization": "Some String Org",
                "author": None,
                "tags": "not-a-list",
                "resources": None,
                "metadata_modified": None,
            },
            {"title": "No slug here", "notes": "skipped: missing name"},
            {"name": "no-title", "id": "no-title"},
            "not-a-mapping",
        ],
    },
}


def _mock(respx_mock, payload: object = _PAYLOAD):
    """Mock the CKAN package_search endpoint with *payload*."""
    return respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=payload),
    )


def _provider() -> UkOpenDataProvider:
    """Return a fresh provider instance for each test."""
    return UkOpenDataProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "uk_open_data"
    assert p.tags == ["web", "gov", "data", "knowledge"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "uk_open_data" in registry
    assert registry["uk_open_data"].tags == ["web", "gov", "data", "knowledge"]


@pytest.mark.asyncio
async def test_search_builds_structured_result(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("flood", SearchParams(num_results=10))
    dataset = result.results[0]

    assert dataset.title == "Flooding"
    assert dataset.url == ("https://ckan.publishing.service.gov.uk/dataset/flooding2")
    assert dataset.source == "ckan.publishing.service.gov.uk"
    assert dataset.provider == "uk_open_data"
    assert dataset.rank == 1
    assert dataset.published_date == "2026-09-25"
    # HTML tags are stripped from the description in the snippet.
    assert dataset.snippet == (
        "Details of flood recovery work in the Calder valley. | "
        "Organization: Calderdale Metropolitan Borough Council | "
        "Author: Calderdale Council | "
        "Tags: flooding, environment | "
        "Formats: CSV, GeoJSON | "
        "Resources: 7 | "
        "License: UK Open Government Licence (OGL)"
    )
    assert dataset.extra == {
        "id": "b2cc36a7-33d3-43de-81d5-f7038c34dd1a",
        "name": "flooding2",
        "organization": "Calderdale Metropolitan Borough Council",
        "author": "Calderdale Council",
        "tags": ["flooding", "environment"],
        "formats": ["CSV", "GeoJSON"],
        "resources": 7,
        "license": "UK Open Government Licence (OGL)",
        "is_open": True,
        "landing_page": "https://dataworks.calderdale.gov.uk/dataset/flooding-e50rg",
        "updated": "2026-09-25",
    }


@pytest.mark.asyncio
async def test_search_accepts_string_organization_and_missing_metadata(
    respx_mock,
) -> None:
    _mock(respx_mock)

    result = await _provider().search("flood", SearchParams(num_results=10))
    bare = result.results[1]

    assert bare.title == "Bare Dataset"
    assert bare.url == "https://ckan.publishing.service.gov.uk/dataset/bare-dataset"
    assert bare.rank == 2
    # No description, so the snippet leads with the organization.
    assert bare.snippet == "Organization: Some String Org"
    assert bare.published_date is None
    assert bare.extra["organization"] == "Some String Org"
    assert bare.extra["author"] is None
    assert bare.extra["tags"] == []
    assert bare.extra["formats"] == []
    assert bare.extra["resources"] == 0
    assert bare.extra["license"] is None
    assert bare.extra["is_open"] is False
    assert bare.extra["landing_page"] is None
    assert bare.extra["updated"] is None


@pytest.mark.asyncio
async def test_search_skips_incomplete_and_malformed_entries(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("flood", SearchParams(num_results=10))

    assert [r.title for r in result.results] == [
        "Flooding",
        "Bare Dataset",
    ]
    assert [r.rank for r in result.results] == [1, 2]


@pytest.mark.asyncio
async def test_search_deduplicates_by_id(respx_mock) -> None:
    duplicate = {
        "title": "Same dataset",
        "name": "same-dataset",
        "id": "abc",
        "organization": {"title": "Org"},
    }
    _mock(
        respx_mock,
        {"success": True, "result": {"results": [duplicate, dict(duplicate)]}},
    )

    result = await _provider().search("same", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["Same dataset"]


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("flood", SearchParams(num_results=1))

    assert [r.title for r in result.results] == ["Flooding"]


@pytest.mark.asyncio
async def test_search_sends_query_params(respx_mock) -> None:
    route = _mock(respx_mock)

    await _provider().search("renewable energy", SearchParams(num_results=7))

    params = route.calls.last.request.url.params
    assert params["q"] == "renewable energy"
    assert params["rows"] == "7"


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
        {"result": None},
        {"result": {"results": None}},
        {"result": {"results": "nope"}},
    ):
        respx_mock.get(_SEARCH_URL).mock(
            return_value=respx.MockResponse(200, json=payload),
        )
        result = await _provider().search("flood", SearchParams(num_results=5))
        assert result.results == []


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("flood", SearchParams(num_results=5))
