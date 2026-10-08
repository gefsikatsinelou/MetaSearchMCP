"""Unit tests for the Italian national open data portal provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.it_open_data import ItOpenDataProvider

_SEARCH_URL = "https://dati.gov.it/opendata/api/3/action/package_search"

_PAYLOAD = {
    "success": True,
    "result": {
        "count": 885,
        "results": [
            {
                "title": "Acqua - Corsi di acqua - Catasto",
                "name": "acqua-corsi-di-acqua-catasto",
                "id": "c45f2c33-9bec-4363-afd9-cda81b8a3b91",
                "notes": "Catasto dei <b>corsi d'acqua</b> regionali.",
                "author": "Regione Sardegna",
                "organization": {
                    "title": "GeoDati - RNDT",
                    "name": "geodati-gov-it-rndt",
                },
                "tags": [
                    {"name": "acqua", "display_name": "acqua"},
                    {"name": "acqua", "display_name": "acqua"},
                    {"display_name": "Idrografia"},
                ],
                "resources": [
                    {"format": "SHP"},
                    {"format": "CSV"},
                    {"format": "SHP"},
                ],
                "license_title": (
                    "Creative Commons Attribuzione 4.0 Internazionale (CC BY 4.0)"
                ),
                "isopen": True,
                "issued": "2023-12-06",
                "num_resources": 1,
                "metadata_modified": "2026-09-19T12:10:43.088209",
                "url": "https://example.it/dataset/acqua",
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


def _provider() -> ItOpenDataProvider:
    """Return a fresh provider instance for each test."""
    return ItOpenDataProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "it_open_data"
    assert p.tags == ["web", "gov", "data", "knowledge"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "it_open_data" in registry
    assert registry["it_open_data"].tags == ["web", "gov", "data", "knowledge"]


@pytest.mark.asyncio
async def test_search_builds_structured_result(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("acqua", SearchParams(num_results=10))
    dataset = result.results[0]

    assert dataset.title == "Acqua - Corsi di acqua - Catasto"
    assert dataset.url == (
        "https://www.dati.gov.it/dataset/acqua-corsi-di-acqua-catasto"
    )
    assert dataset.source == "dati.gov.it"
    assert dataset.provider == "it_open_data"
    assert dataset.rank == 1
    assert dataset.published_date == "2023-12-06"
    # HTML tags are stripped from the description in the snippet.
    assert dataset.snippet == (
        "Catasto dei corsi d'acqua regionali. | "
        "Organization: GeoDati - RNDT | "
        "Author: Regione Sardegna | "
        "Tags: acqua, Idrografia | "
        "Formats: SHP, CSV | "
        "Resources: 1 | "
        "License: Creative Commons Attribuzione 4.0 Internazionale (CC BY 4.0)"
    )
    assert dataset.extra == {
        "id": "c45f2c33-9bec-4363-afd9-cda81b8a3b91",
        "name": "acqua-corsi-di-acqua-catasto",
        "organization": "GeoDati - RNDT",
        "author": "Regione Sardegna",
        "tags": ["acqua", "Idrografia"],
        "formats": ["SHP", "CSV"],
        "resources": 1,
        "license": "Creative Commons Attribuzione 4.0 Internazionale (CC BY 4.0)",
        "is_open": True,
        "landing_page": "https://example.it/dataset/acqua",
        "issued": "2023-12-06",
        "updated": "2026-09-19",
    }


@pytest.mark.asyncio
async def test_search_accepts_string_organization_and_missing_metadata(
    respx_mock,
) -> None:
    _mock(respx_mock)

    result = await _provider().search("acqua", SearchParams(num_results=10))
    bare = result.results[1]

    assert bare.title == "Bare Dataset"
    assert bare.url == "https://www.dati.gov.it/dataset/bare-dataset"
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
async def test_search_reads_dates_from_extras(respx_mock) -> None:
    _mock(
        respx_mock,
        {
            "success": True,
            "result": {
                "results": [
                    {
                        "name": "extras-dataset",
                        "title": "Extras Title",
                        "extras": [
                            {"key": "issued", "value": "2020-01-02"},
                            {"key": "modified", "value": "2021-06-07T09:00:00"},
                        ],
                    },
                ],
            },
        },
    )

    result = await _provider().search("extras", SearchParams(num_results=5))
    dataset = result.results[0]

    assert dataset.published_date == "2020-01-02"
    assert dataset.extra["issued"] == "2020-01-02"
    assert dataset.extra["updated"] == "2021-06-07"


@pytest.mark.asyncio
async def test_search_skips_incomplete_and_malformed_entries(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("acqua", SearchParams(num_results=10))

    assert [r.title for r in result.results] == [
        "Acqua - Corsi di acqua - Catasto",
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

    result = await _provider().search("acqua", SearchParams(num_results=1))

    assert [r.title for r in result.results] == [
        "Acqua - Corsi di acqua - Catasto",
    ]


@pytest.mark.asyncio
async def test_search_sends_query_params(respx_mock) -> None:
    route = _mock(respx_mock)

    await _provider().search("energie rinnovabili", SearchParams(num_results=7))

    params = route.calls.last.request.url.params
    assert params["q"] == "energie rinnovabili"
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
        result = await _provider().search("acqua", SearchParams(num_results=5))
        assert result.results == []


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("acqua", SearchParams(num_results=5))
