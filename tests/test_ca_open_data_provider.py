"""Unit tests for the Government of Canada open data portal provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.ca_open_data import CaOpenDataProvider

_SEARCH_URL = "https://open.canada.ca/data/api/3/action/package_search"

_PAYLOAD = {
    "success": True,
    "result": {
        "count": 2861,
        "results": [
            {
                "title": "Climatic Regions",
                "name": "09ffaeb5-ec8f-5bb5-bdcb-3436ccf26f58",
                "id": "09ffaeb5-ec8f-5bb5-bdcb-3436ccf26f58",
                "notes": (
                    "<p>Contained within the Atlas of Canada is a map of "
                    "climatic regions.</p>"
                ),
                "author": "Environment Canada",
                "organization": {
                    "title": "Natural Resources Canada",
                    "name": "nrcan-rncan",
                },
                "keywords": {
                    "en": ["climate", "weather", "weather"],
                    "fr": ["climat", "météorologie"],
                },
                "subject": [
                    "nature_and_environment",
                    "science_and_technology",
                    "nature_and_environment",
                ],
                "resources": [
                    {"format": "CSV"},
                    {"format": "GeoJSON"},
                    {"format": "CSV"},
                ],
                "license_title": "Open Government Licence - Canada",
                "isopen": True,
                "jurisdiction": "federal",
                "num_resources": 7,
                "date_published": "1957-01-01 00:00:00",
                "metadata_modified": "2026-09-25T11:50:26.789461",
                "url": {
                    "en": "https://geogratis.gc.ca/api/en/nrcan",
                    "fr": "https://geogratis.gc.ca/api/fr/nrcan",
                },
            },
            {
                "title": "Bare Dataset",
                "name": "bare-dataset",
                "organization": "Some String Org",
                "author": None,
                "keywords": "not-a-mapping",
                "subject": None,
                "resources": None,
                "date_published": None,
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


def _provider() -> CaOpenDataProvider:
    """Return a fresh provider instance for each test."""
    return CaOpenDataProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "ca_open_data"
    assert p.tags == ["web", "gov", "data", "knowledge"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "ca_open_data" in registry
    assert registry["ca_open_data"].tags == ["web", "gov", "data", "knowledge"]


@pytest.mark.asyncio
async def test_search_builds_structured_result(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("climate", SearchParams(num_results=10))
    dataset = result.results[0]

    assert dataset.title == "Climatic Regions"
    assert dataset.url == (
        "https://open.canada.ca/data/en/dataset/09ffaeb5-ec8f-5bb5-bdcb-3436ccf26f58"
    )
    assert dataset.source == "open.canada.ca"
    assert dataset.provider == "ca_open_data"
    assert dataset.rank == 1
    assert dataset.published_date == "1957-01-01"
    # HTML tags are stripped from the description in the snippet.
    assert dataset.snippet == (
        "Contained within the Atlas of Canada is a map of climatic regions. | "
        "Organization: Natural Resources Canada | "
        "Author: Environment Canada | "
        "Keywords: climate, weather | "
        "Subjects: nature_and_environment, science_and_technology | "
        "Formats: CSV, GeoJSON | "
        "Resources: 7 | "
        "License: Open Government Licence - Canada"
    )
    assert dataset.extra == {
        "id": "09ffaeb5-ec8f-5bb5-bdcb-3436ccf26f58",
        "name": "09ffaeb5-ec8f-5bb5-bdcb-3436ccf26f58",
        "organization": "Natural Resources Canada",
        "author": "Environment Canada",
        "keywords": ["climate", "weather"],
        "subjects": ["nature_and_environment", "science_and_technology"],
        "formats": ["CSV", "GeoJSON"],
        "resources": 7,
        "license": "Open Government Licence - Canada",
        "is_open": True,
        "jurisdiction": "federal",
        "landing_page": "https://geogratis.gc.ca/api/en/nrcan",
        "published": "1957-01-01",
        "updated": "2026-09-25",
    }


@pytest.mark.asyncio
async def test_search_accepts_string_organization_and_missing_metadata(
    respx_mock,
) -> None:
    _mock(respx_mock)

    result = await _provider().search("climate", SearchParams(num_results=10))
    bare = result.results[1]

    assert bare.title == "Bare Dataset"
    assert bare.url == "https://open.canada.ca/data/en/dataset/bare-dataset"
    assert bare.rank == 2
    # No description, so the snippet leads with the organization.
    assert bare.snippet == "Organization: Some String Org"
    assert bare.published_date is None
    assert bare.extra["organization"] == "Some String Org"
    assert bare.extra["author"] is None
    assert bare.extra["keywords"] == []
    assert bare.extra["subjects"] == []
    assert bare.extra["formats"] == []
    assert bare.extra["resources"] == 0
    assert bare.extra["license"] is None
    assert bare.extra["is_open"] is False
    assert bare.extra["jurisdiction"] is None
    assert bare.extra["landing_page"] is None
    assert bare.extra["published"] is None
    assert bare.extra["updated"] is None


@pytest.mark.asyncio
async def test_search_falls_back_to_translated_fields(respx_mock) -> None:
    _mock(
        respx_mock,
        {
            "success": True,
            "result": {
                "results": [
                    {
                        "name": "translated-dataset",
                        "title_translated": {"en": "Translated Title"},
                        "notes_translated": {"en": "Translated description."},
                    },
                ],
            },
        },
    )

    result = await _provider().search("translated", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["Translated Title"]
    assert result.results[0].snippet.startswith("Translated description.")


@pytest.mark.asyncio
async def test_search_skips_incomplete_and_malformed_entries(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("climate", SearchParams(num_results=10))

    assert [r.title for r in result.results] == [
        "Climatic Regions",
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

    assert [r.title for r in result.results] == ["Climatic Regions"]


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
