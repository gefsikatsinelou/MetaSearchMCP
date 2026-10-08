"""Unit tests for the Irish national open data portal provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.ie_open_data import IeOpenDataProvider

_SEARCH_URL = "https://data.gov.ie/api/3/action/package_search"

_PAYLOAD = {
    "success": True,
    "result": {
        "count": 1204,
        "results": [
            {
                "title": "Climate Change",
                "name": "climate-change2",
                "id": "c11d1485-302a-4f2c-9835-767ee8054202",
                "notes": ("<p>Climate change projections for <b>Ireland</b>.</p>"),
                "author": "Met Eireann",
                "organization": {
                    "title": "Department of Climate, Energy and the Environment",
                    "name": "department-of-climate-energy-and-environment",
                },
                "tags": [
                    {"name": "climate change", "display_name": "climate change"},
                    {"name": "climate change", "display_name": "climate change"},
                    {"display_name": "Marine Spatial Planning"},
                ],
                "resources": [
                    {"format": "CSV"},
                    {"format": "JSON"},
                    {"format": "CSV"},
                ],
                "license_title": "Creative Commons Attribution 4.0",
                "isopen": True,
                "issued": "2024-09-11",
                "num_resources": 6,
                "metadata_modified": "2026-10-07T16:53:12.751695",
                "url": "https://example.ie/dataset/climate",
            },
            {
                "title": "Bare Dataset",
                "name": "bare-dataset",
                "organization": "Some String Org",
                "author": None,
                "tags": None,
                "resources": None,
                "issued": None,
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


def _provider() -> IeOpenDataProvider:
    """Return a fresh provider instance for each test."""
    return IeOpenDataProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "ie_open_data"
    assert p.tags == ["web", "gov", "data", "knowledge"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "ie_open_data" in registry
    assert registry["ie_open_data"].tags == ["web", "gov", "data", "knowledge"]


@pytest.mark.asyncio
async def test_search_builds_structured_result(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("climate", SearchParams(num_results=10))
    dataset = result.results[0]

    assert dataset.title == "Climate Change"
    assert dataset.url == "https://data.gov.ie/dataset/climate-change2"
    assert dataset.source == "data.gov.ie"
    assert dataset.provider == "ie_open_data"
    assert dataset.rank == 1
    assert dataset.published_date == "2024-09-11"
    # HTML tags are stripped from the description in the snippet.
    assert dataset.snippet == (
        "Climate change projections for Ireland . | "
        "Organization: Department of Climate, Energy and the Environment | "
        "Author: Met Eireann | "
        "Tags: climate change, Marine Spatial Planning | "
        "Formats: CSV, JSON | "
        "Resources: 6 | "
        "License: Creative Commons Attribution 4.0"
    )
    assert dataset.extra == {
        "id": "c11d1485-302a-4f2c-9835-767ee8054202",
        "name": "climate-change2",
        "organization": "Department of Climate, Energy and the Environment",
        "author": "Met Eireann",
        "tags": ["climate change", "Marine Spatial Planning"],
        "formats": ["CSV", "JSON"],
        "resources": 6,
        "license": "Creative Commons Attribution 4.0",
        "is_open": True,
        "landing_page": "https://example.ie/dataset/climate",
        "issued": "2024-09-11",
        "updated": "2026-10-07",
    }


@pytest.mark.asyncio
async def test_search_accepts_string_organization_and_missing_metadata(
    respx_mock,
) -> None:
    _mock(respx_mock)

    result = await _provider().search("climate", SearchParams(num_results=10))
    bare = result.results[1]

    assert bare.title == "Bare Dataset"
    assert bare.url == "https://data.gov.ie/dataset/bare-dataset"
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
    assert bare.extra["issued"] is None
    assert bare.extra["updated"] is None


@pytest.mark.asyncio
async def test_search_falls_back_to_modified_when_no_issued(respx_mock) -> None:
    _mock(
        respx_mock,
        {
            "success": True,
            "result": {
                "results": [
                    {
                        "name": "fallback-dataset",
                        "title": "Fallback Title",
                        "metadata_modified": "2025-03-04T10:00:00",
                    },
                ],
            },
        },
    )

    result = await _provider().search("fallback", SearchParams(num_results=5))

    assert result.results[0].published_date == "2025-03-04"


@pytest.mark.asyncio
async def test_search_skips_incomplete_and_malformed_entries(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("climate", SearchParams(num_results=10))

    assert [r.title for r in result.results] == [
        "Climate Change",
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

    result = await _provider().search("climate", SearchParams(num_results=1))

    assert [r.title for r in result.results] == ["Climate Change"]


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
        result = await _provider().search("climate", SearchParams(num_results=5))
        assert result.results == []


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("climate", SearchParams(num_results=5))
