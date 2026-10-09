"""Unit tests for the Dutch open data portal (data.overheid.nl) provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.nl_open_data import NlOpenDataProvider

_SEARCH_URL = "https://data.overheid.nl/data/api/3/action/package_search"

_PAYLOAD = {
    "success": True,
    "result": {
        "count": 306,
        "results": [
            {
                "id": "nl-1",
                "name": "luchtkwaliteit-gemeente-groningen",
                "title": "Luchtkwaliteit gemeente Groningen",
                "notes": "<p>Metingen van luchtkwaliteit.</p>",
                "organization": {
                    "title": "Gemeente Groningen",
                    "name": "groningen",
                },
                "publisher": (
                    "http://standaarden.overheid.nl/owms/terms/Groningen_(gemeente)"
                ),
                "authority": (
                    "http://standaarden.overheid.nl/owms/terms/Groningen_(gemeente)"
                ),
                "author": None,
                "maintainer": "Gemeente Groningen",
                "tags": [
                    {"name": "luchtkwaliteit"},
                    {"name": "milieu"},
                    {"name": "luchtkwaliteit"},
                ],
                "groups": [],
                "theme": [
                    "http://standaarden.overheid.nl/owms/terms/Lucht",
                    ("http://standaarden.overheid.nl/owms/terms/Natuur_en_milieu"),
                ],
                "resources": [
                    {
                        "format": (
                            "http://publications.europa.eu/resource/"
                            "authority/file-type/PDF"
                        )
                    },
                    {
                        "format": (
                            "http://publications.europa.eu/resource/"
                            "authority/file-type/CSV"
                        )
                    },
                    {"format": "PDF"},
                ],
                "license_title": "CC-BY (4.0)",
                "isopen": False,
                "num_resources": 2,
                "metadata_created": "2024-05-02T11:53:25.977300",
                "metadata_modified": "2025-06-04T14:07:48.998427",
                "language": [
                    "http://publications.europa.eu/resource/authority/language/NLD"
                ],
                "frequency": (
                    "http://publications.europa.eu/resource/authority/frequency/CONT"
                ),
                "dataset_status": "http://data.overheid.nl/status/beschikbaar",
                "access_rights": (
                    "http://publications.europa.eu/resource/"
                    "authority/access-right/PUBLIC"
                ),
                "source_catalog": "https://data.groningen.nl",
            },
            {
                "title": "Bare Dataset",
                "name": "bare-dataset",
                "organization": "Some String Org",
                "author": None,
                "tags": "not-a-list",
                "groups": None,
                "theme": None,
                "resources": None,
                "license_title": None,
                "metadata_modified": None,
                "metadata_created": None,
            },
            {"title": "No slug here", "notes": "skipped: missing name"},
            {"name": "no-title", "id": "no-title"},
            "not-a-mapping",
        ],
    },
}


def _mock(respx_mock, payload: object = _PAYLOAD):
    """Mock the data.overheid.nl package_search endpoint with *payload*."""
    return respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=payload),
    )


def _provider() -> NlOpenDataProvider:
    """Return a fresh provider instance for each test."""
    return NlOpenDataProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "nl_open_data"
    assert p.tags == ["web", "gov", "data", "knowledge"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "nl_open_data" in registry
    assert registry["nl_open_data"].tags == ["web", "gov", "data", "knowledge"]


@pytest.mark.asyncio
async def test_search_builds_structured_result(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("luchtkwaliteit", SearchParams(num_results=10))
    dataset = result.results[0]

    assert dataset.title == "Luchtkwaliteit gemeente Groningen"
    assert dataset.url == (
        "https://data.overheid.nl/dataset/luchtkwaliteit-gemeente-groningen"
    )
    assert dataset.source == "data.overheid.nl"
    assert dataset.provider == "nl_open_data"
    assert dataset.rank == 1
    assert dataset.published_date == "2024-05-02"
    # HTML tags are stripped, OWMS URIs are reduced to readable labels.
    assert dataset.snippet == (
        "Metingen van luchtkwaliteit. | "
        "Organization: Gemeente Groningen | "
        "Publisher: Groningen | "
        "Authority: Groningen | "
        "Tags: luchtkwaliteit, milieu | "
        "Categories: Lucht, Natuur en milieu | "
        "Formats: PDF, CSV | "
        "Resources: 2 | "
        "License: CC-BY (4.0)"
    )
    assert dataset.extra == {
        "id": "nl-1",
        "name": "luchtkwaliteit-gemeente-groningen",
        "organization": "Gemeente Groningen",
        "publisher": "Groningen",
        "authority": "Groningen",
        "author": "Gemeente Groningen",
        "tags": ["luchtkwaliteit", "milieu"],
        "categories": ["Lucht", "Natuur en milieu"],
        "formats": ["PDF", "CSV"],
        "resources": 2,
        "license": "CC-BY (4.0)",
        "is_open": False,
        "language": ["NLD"],
        "frequency": "CONT",
        "dataset_status": "beschikbaar",
        "access_rights": "PUBLIC",
        "source_catalog": "https://data.groningen.nl",
        "published": "2024-05-02",
        "updated": "2025-06-04",
    }


@pytest.mark.asyncio
async def test_search_accepts_string_organization_and_missing_metadata(
    respx_mock,
) -> None:
    _mock(respx_mock)

    result = await _provider().search("luchtkwaliteit", SearchParams(num_results=10))
    bare = result.results[1]

    assert bare.title == "Bare Dataset"
    assert bare.url == "https://data.overheid.nl/dataset/bare-dataset"
    assert bare.rank == 2
    # No description, so the snippet leads with the organization.
    assert bare.snippet == "Organization: Some String Org"
    assert bare.published_date is None
    assert bare.extra == {
        "id": None,
        "name": "bare-dataset",
        "organization": "Some String Org",
        "publisher": None,
        "authority": None,
        "author": None,
        "tags": [],
        "categories": [],
        "formats": [],
        "resources": 0,
        "license": None,
        "is_open": False,
        "language": [],
        "frequency": None,
        "dataset_status": None,
        "access_rights": None,
        "source_catalog": None,
        "published": None,
        "updated": None,
    }


@pytest.mark.asyncio
async def test_search_uses_modified_date_when_created_absent(respx_mock) -> None:
    _mock(
        respx_mock,
        {
            "success": True,
            "result": {
                "results": [
                    {
                        "title": "Modified only",
                        "name": "modified-only",
                        "modified": "2025-01-09T08:00:00",
                    },
                ],
            },
        },
    )

    result = await _provider().search("modified", SearchParams(num_results=5))

    assert result.results[0].published_date == "2025-01-09"


@pytest.mark.asyncio
async def test_search_skips_incomplete_and_malformed_entries(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("luchtkwaliteit", SearchParams(num_results=10))

    assert [r.title for r in result.results] == [
        "Luchtkwaliteit gemeente Groningen",
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

    result = await _provider().search("luchtkwaliteit", SearchParams(num_results=1))

    assert [r.title for r in result.results] == [
        "Luchtkwaliteit gemeente Groningen",
    ]


@pytest.mark.asyncio
async def test_search_sends_query_params(respx_mock) -> None:
    route = _mock(respx_mock)

    await _provider().search("water kwaliteit", SearchParams(num_results=7))

    params = route.calls.last.request.url.params
    assert params["q"] == "water kwaliteit"
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
        result = await _provider().search("luchtkwaliteit", SearchParams(num_results=5))
        assert result.results == []


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("luchtkwaliteit", SearchParams(num_results=5))
