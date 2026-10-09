"""Unit tests for the GovData (German open data portal) provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.govdata_de import GovDataDeProvider

_SEARCH_URL = "https://ckan.govdata.de/api/3/action/package_search"

_PAYLOAD = {
    "success": True,
    "result": {
        "count": 189,
        "results": [
            {
                "title": "Wetter in Potsdam",
                "name": "wetter-in-potsdam",
                "id": "abc-123",
                "notes": "<p>Stündliche Wetterdaten für Potsdam.</p>",
                "author": None,
                "maintainer": "LHP",
                "organization": {
                    "title": "Landeshauptstadt Potsdam",
                    "name": "potsdam",
                },
                "tags": [
                    {"name": "wetter"},
                    {"name": "klima"},
                    {"name": "wetter"},
                ],
                "groups": [
                    {"title": "Umwelt", "name": "envi"},
                    {
                        "title": "Geographie, Geologie und Geobasisdaten",
                        "name": "geog",
                    },
                ],
                "resources": [
                    {
                        "format": (
                            "http://publications.europa.eu/resource/"
                            "authority/file-type/CSV"
                        )
                    },
                    {
                        "format": (
                            "http://publications.europa.eu/resource/"
                            "authority/file-type/JSON"
                        )
                    },
                    {"format": "CSV"},
                ],
                "license_title": "Creative Commons Namensnennung",
                "isopen": True,
                "num_resources": 2,
                "metadata_created": "2024-06-12T17:02:16.179954",
                "metadata_modified": "2024-07-31T10:55:20.477998",
                "extras": [
                    {"key": "publisher_name", "value": "LHP"},
                    {
                        "key": "theme",
                        "value": (
                            '["http://publications.europa.eu/resource/'
                            'authority/data-theme/ENVI"]'
                        ),
                    },
                    {"key": "issued", "value": "2023-10-26T07:14:36+00:00"},
                    {"key": "modified", "value": "2023-10-26T07:14:36+00:00"},
                    {
                        "key": "metadata_harvested_portal",
                        "value": "https://opendata.potsdam.de",
                    },
                ],
            },
            {
                "title": "Bare Dataset",
                "name": "bare-dataset",
                "organization": "Some String Org",
                "author": None,
                "tags": "not-a-list",
                "groups": None,
                "resources": None,
                "license_title": None,
                "metadata_modified": None,
                "metadata_created": None,
                "extras": "not-a-list",
            },
            {"title": "No slug here", "notes": "skipped: missing name"},
            {"name": "no-title", "id": "no-title"},
            "not-a-mapping",
        ],
    },
}


def _mock(respx_mock, payload: object = _PAYLOAD):
    """Mock the GovData package_search endpoint with *payload*."""
    return respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=payload),
    )


def _provider() -> GovDataDeProvider:
    """Return a fresh provider instance for each test."""
    return GovDataDeProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "govdata_de"
    assert p.tags == ["web", "gov", "data", "knowledge"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "govdata_de" in registry
    assert registry["govdata_de"].tags == ["web", "gov", "data", "knowledge"]


@pytest.mark.asyncio
async def test_search_builds_structured_result(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("wetter", SearchParams(num_results=10))
    dataset = result.results[0]

    assert dataset.title == "Wetter in Potsdam"
    assert dataset.url == "https://www.govdata.de/suche/daten/wetter-in-potsdam"
    assert dataset.source == "www.govdata.de"
    assert dataset.provider == "govdata_de"
    assert dataset.rank == 1
    assert dataset.published_date == "2023-10-26"
    # HTML tags are stripped from the description in the snippet.
    assert dataset.snippet == (
        "Stündliche Wetterdaten für Potsdam. | "
        "Organization: Landeshauptstadt Potsdam | "
        "Publisher: LHP | "
        "Author: LHP | "
        "Tags: wetter, klima | "
        "Categories: Umwelt, Geographie, Geologie und Geobasisdaten | "
        "Formats: CSV, JSON | "
        "Resources: 2 | "
        "License: Creative Commons Namensnennung"
    )
    assert dataset.extra == {
        "id": "abc-123",
        "name": "wetter-in-potsdam",
        "organization": "Landeshauptstadt Potsdam",
        "publisher": "LHP",
        "author": "LHP",
        "tags": ["wetter", "klima"],
        "categories": ["Umwelt", "Geographie, Geologie und Geobasisdaten"],
        "formats": ["CSV", "JSON"],
        "resources": 2,
        "license": "Creative Commons Namensnennung",
        "is_open": True,
        "theme": (
            '["http://publications.europa.eu/resource/authority/data-theme/ENVI"]'
        ),
        "harvested_portal": "https://opendata.potsdam.de",
        "published": "2023-10-26",
        "updated": "2024-07-31",
    }


@pytest.mark.asyncio
async def test_search_accepts_string_organization_and_missing_metadata(
    respx_mock,
) -> None:
    _mock(respx_mock)

    result = await _provider().search("wetter", SearchParams(num_results=10))
    bare = result.results[1]

    assert bare.title == "Bare Dataset"
    assert bare.url == "https://www.govdata.de/suche/daten/bare-dataset"
    assert bare.rank == 2
    # No description, so the snippet leads with the organization.
    assert bare.snippet == "Organization: Some String Org"
    assert bare.published_date is None
    assert bare.extra == {
        "id": None,
        "name": "bare-dataset",
        "organization": "Some String Org",
        "publisher": None,
        "author": None,
        "tags": [],
        "categories": [],
        "formats": [],
        "resources": 0,
        "license": None,
        "is_open": False,
        "theme": None,
        "harvested_portal": None,
        "published": None,
        "updated": None,
    }


@pytest.mark.asyncio
async def test_search_uses_created_date_when_issued_absent(respx_mock) -> None:
    _mock(
        respx_mock,
        {
            "success": True,
            "result": {
                "results": [
                    {
                        "title": "Created only",
                        "name": "created-only",
                        "metadata_created": "2024-06-12T17:02:16.179954",
                    },
                ],
            },
        },
    )

    result = await _provider().search("created", SearchParams(num_results=5))

    assert result.results[0].published_date == "2024-06-12"


@pytest.mark.asyncio
async def test_search_skips_incomplete_and_malformed_entries(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("wetter", SearchParams(num_results=10))

    assert [r.title for r in result.results] == [
        "Wetter in Potsdam",
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

    result = await _provider().search("wetter", SearchParams(num_results=1))

    assert [r.title for r in result.results] == ["Wetter in Potsdam"]


@pytest.mark.asyncio
async def test_search_sends_query_params(respx_mock) -> None:
    route = _mock(respx_mock)

    await _provider().search("erneuerbare Energie", SearchParams(num_results=7))

    params = route.calls.last.request.url.params
    assert params["q"] == "erneuerbare Energie"
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
        result = await _provider().search("wetter", SearchParams(num_results=5))
        assert result.results == []


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("wetter", SearchParams(num_results=5))
