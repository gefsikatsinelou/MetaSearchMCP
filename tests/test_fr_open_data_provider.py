"""Unit tests for the French national open data portal provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.fr_open_data import FrOpenDataProvider

_SEARCH_URL = "https://www.data.gouv.fr/api/1/datasets/"

_PAYLOAD = {
    "data": [
        {
            "title": "Plan Climat Air Energie territorial",
            "slug": "plan-climat-air-energie-territorial",
            "id": "67377b46b034c8d8c3c40aff",
            "description": "Avancement des <b>PCAET</b> en Loire-Atlantique.",
            "organization": {
                "name": "Direction Départementale des Territoires",
                "acronym": "DDTM 44",
            },
            "tags": ["air", "climat", "climat", "energie"],
            "resources": [
                {"format": "esri shapefile (shp)"},
                {"format": "csv"},
                {"format": "csv"},
            ],
            "license": "lov2",
            "created_at": "2023-06-19T00:00:00+00:00",
            "last_update": "2026-04-21T00:00:00+00:00",
            "page": (
                "https://www.data.gouv.fr/datasets/plan-climat-air-energie-territorial"
            ),
        },
        {
            "title": "Bare Dataset",
            "slug": "bare-dataset",
            "organization": None,
            "tags": None,
            "resources": None,
            "created_at": None,
            "last_update": None,
        },
        {"title": "No slug here", "description": "skipped: missing slug"},
        {"slug": "no-title", "id": "no-title"},
        "not-a-mapping",
    ],
    "total": 88,
    "page": 1,
    "page_size": 2,
}


def _mock(respx_mock, payload: object = _PAYLOAD):
    """Mock the data.gouv.fr dataset search endpoint with *payload*."""
    return respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=payload),
    )


def _provider() -> FrOpenDataProvider:
    """Return a fresh provider instance for each test."""
    return FrOpenDataProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "fr_open_data"
    assert p.tags == ["web", "gov", "data", "knowledge"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "fr_open_data" in registry
    assert registry["fr_open_data"].tags == ["web", "gov", "data", "knowledge"]


@pytest.mark.asyncio
async def test_search_builds_structured_result(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("climat", SearchParams(num_results=10))
    dataset = result.results[0]

    assert dataset.title == "Plan Climat Air Energie territorial"
    assert dataset.url == (
        "https://www.data.gouv.fr/datasets/plan-climat-air-energie-territorial"
    )
    assert dataset.source == "data.gouv.fr"
    assert dataset.provider == "fr_open_data"
    assert dataset.rank == 1
    assert dataset.published_date == "2023-06-19"
    # HTML tags are stripped from the description in the snippet.
    assert dataset.snippet == (
        "Avancement des PCAET en Loire-Atlantique. | "
        "Organization: Direction Départementale des Territoires (DDTM 44) | "
        "Tags: air, climat, energie | "
        "Formats: esri shapefile (shp), csv | "
        "Resources: 3 | "
        "License: lov2"
    )
    assert dataset.extra == {
        "id": "67377b46b034c8d8c3c40aff",
        "slug": "plan-climat-air-energie-territorial",
        "organization": "Direction Départementale des Territoires (DDTM 44)",
        "tags": ["air", "climat", "energie"],
        "formats": ["esri shapefile (shp)", "csv"],
        "resources": 3,
        "license": "lov2",
        "created": "2023-06-19",
        "updated": "2026-04-21",
    }


@pytest.mark.asyncio
async def test_search_accepts_missing_metadata(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("climat", SearchParams(num_results=10))
    bare = result.results[1]

    assert bare.title == "Bare Dataset"
    assert bare.url == "https://www.data.gouv.fr/datasets/bare-dataset"
    assert bare.rank == 2
    assert bare.snippet == ""
    assert bare.published_date is None
    assert bare.extra["organization"] is None
    assert bare.extra["tags"] == []
    assert bare.extra["formats"] == []
    assert bare.extra["resources"] == 0
    assert bare.extra["license"] is None
    assert bare.extra["created"] is None
    assert bare.extra["updated"] is None


@pytest.mark.asyncio
async def test_search_builds_url_from_slug_when_page_absent(respx_mock) -> None:
    _mock(
        respx_mock,
        {"data": [{"title": "No page", "slug": "no-page", "id": "np1"}]},
    )

    result = await _provider().search("no page", SearchParams(num_results=5))

    assert result.results[0].url == "https://www.data.gouv.fr/datasets/no-page"


@pytest.mark.asyncio
async def test_search_falls_back_to_last_modified_when_no_created(
    respx_mock,
) -> None:
    _mock(
        respx_mock,
        {
            "data": [
                {
                    "title": "Fallback",
                    "slug": "fallback",
                    "last_modified": "2025-03-04T10:00:00",
                },
            ],
        },
    )

    result = await _provider().search("fallback", SearchParams(num_results=5))

    assert result.results[0].published_date == "2025-03-04"


@pytest.mark.asyncio
async def test_search_skips_incomplete_and_malformed_entries(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("climat", SearchParams(num_results=10))

    assert [r.title for r in result.results] == [
        "Plan Climat Air Energie territorial",
        "Bare Dataset",
    ]
    assert [r.rank for r in result.results] == [1, 2]


@pytest.mark.asyncio
async def test_search_deduplicates_by_id(respx_mock) -> None:
    duplicate = {
        "title": "Same dataset",
        "slug": "same-dataset",
        "id": "abc",
    }
    _mock(respx_mock, {"data": [duplicate, dict(duplicate)]})

    result = await _provider().search("same", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["Same dataset"]


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("climat", SearchParams(num_results=1))

    assert [r.title for r in result.results] == [
        "Plan Climat Air Energie territorial",
    ]


@pytest.mark.asyncio
async def test_search_sends_query_params(respx_mock) -> None:
    route = _mock(respx_mock)

    await _provider().search("énergie climat", SearchParams(num_results=7))

    params = route.calls.last.request.url.params
    assert params["q"] == "énergie climat"
    assert params["page_size"] == "7"


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
        {"data": None},
        {"data": "nope"},
    ):
        respx_mock.get(_SEARCH_URL).mock(
            return_value=respx.MockResponse(200, json=payload),
        )
        result = await _provider().search("climat", SearchParams(num_results=5))
        assert result.results == []


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("climat", SearchParams(num_results=5))
