"""Unit tests for the European open data portal provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.eu_open_data import EuOpenDataProvider

_SEARCH_URL = "https://data.europa.eu/api/hub/search/search"

_PAYLOAD = {
    "result": {
        "count": 3,
        "results": [
            {
                "id": "belaqi-air-quality",
                "index": "dataset",
                "title": {
                    "en": "BelAQI Index - Belgian Air Quality Index",
                    "fr": "Indice BelAQI",
                },
                "description": {
                    "en": "Air quality measured at stations in Liège.\nSecond line.",
                    "fr": "Qualité de l'air",
                },
                "resource": "http://data.europa.eu/88u/dataset/belaqi-air-quality",
                "landing_page": [
                    {"resource": "https://www.odwb.be/explore/dataset/belaqi/"},
                ],
                "publisher": {"type": "Organization", "name": "City of Liège"},
                "catalog": {
                    "id": "data-gov-be",
                    "title": {"en": "data.gov.be", "fr": "data.gov.be"},
                },
                "country": {"id": "be", "label": "Belgium"},
                "categories": [{"id": "ENVI", "label": {"en": "Environment"}}],
                "keywords": [
                    {"id": "air", "label": "air"},
                    {"id": "air", "label": "air"},
                    {"id": "quality", "label": "quality"},
                ],
                "distributions": [
                    {
                        "id": "d1",
                        "format": {"id": "XML", "label": "XML"},
                        "license": {"id": "cc-by", "label": "CC BY 4.0"},
                    },
                    {"id": "d2", "format": {"id": "CSV", "label": "CSV"}},
                ],
                "modified": "2026-09-08T01:05:14.968Z",
                "issued": "2024-04-15T00:00:00",
                "catalog_record": {"modified": "2026-09-09T00:00:00Z"},
                "access_right": {"label": "public"},
                "is_hvd": True,
            },
            {
                "id": "solar-capacity-lu",
                "title": {"fr": "Énergies renouvelables"},
                "description": None,
                "resource": "http://data.europa.eu/88u/dataset/solar-capacity-lu",
                "publisher": None,
                "creator": [{"name": "SIG-GR"}],
                "catalog": {"title": {"fr": "Plateforme luxembourgeoise"}},
                "country": None,
                "distributions": [{"format": None}, "not-a-mapping"],
                "modified": None,
                "issued": None,
                "catalog_record": {"issued": "2025-01-17T18:15:00Z"},
                "is_hvd": False,
            },
            {"id": "no-title", "title": {}, "resource": "http://example.org/x"},
            {"title": {"en": "No URL"}},
            "not-a-mapping",
        ],
    },
}


def _mock(respx_mock, payload: object = _PAYLOAD):
    """Mock the portal search endpoint with *payload*."""
    return respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=payload),
    )


def _provider() -> EuOpenDataProvider:
    """Return a fresh provider instance for each test."""
    return EuOpenDataProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "eu_open_data"
    assert p.tags == ["web", "gov", "data", "knowledge"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "eu_open_data" in registry
    assert registry["eu_open_data"].tags == ["web", "gov", "data", "knowledge"]


@pytest.mark.asyncio
async def test_search_builds_result_from_dataset(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("air quality", SearchParams(num_results=10))
    dataset = result.results[0]

    assert dataset.title == "BelAQI Index - Belgian Air Quality Index"
    assert dataset.url == (
        "https://data.europa.eu/data/datasets/belaqi-air-quality?locale=en"
    )
    assert dataset.source == "data.europa.eu"
    assert dataset.provider == "eu_open_data"
    assert dataset.rank == 1
    assert dataset.published_date == "2026-09-08"
    assert dataset.snippet == (
        "Air quality measured at stations in Liège. Second line. | "
        "Publisher: City of Liège | Catalogue: data.gov.be | Belgium | "
        "Formats: XML, CSV | License: CC BY 4.0 | Distributions: 2"
    )
    assert dataset.extra == {
        "id": "belaqi-air-quality",
        "publisher": "City of Liège",
        "catalog": "data.gov.be",
        "country": "Belgium",
        "categories": ["Environment"],
        "keywords": ["air", "quality"],
        "formats": ["XML", "CSV"],
        "license": "CC BY 4.0",
        "distributions": 2,
        "updated": "2026-09-08",
        "landing_page": "https://www.odwb.be/explore/dataset/belaqi/",
        "resource": "http://data.europa.eu/88u/dataset/belaqi-air-quality",
        "access_right": "public",
        "high_value_dataset": True,
    }


@pytest.mark.asyncio
async def test_search_falls_back_to_available_translation(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("air", SearchParams(num_results=10))
    fallback = result.results[1]

    # The record carries no English title, so the only translation is used.
    assert fallback.title == "Énergies renouvelables"
    assert fallback.rank == 2
    # Without a publisher object the first creator supplies the publisher.
    assert fallback.extra["publisher"] == "SIG-GR"
    assert fallback.extra["catalog"] == "Plateforme luxembourgeoise"
    assert fallback.extra["country"] is None
    assert fallback.extra["categories"] == []
    assert fallback.extra["keywords"] == []
    assert fallback.extra["formats"] == []
    assert fallback.extra["license"] is None
    # One malformed distribution entry is dropped from the count.
    assert fallback.extra["distributions"] == 1
    assert fallback.extra["updated"] == "2025-01-17"
    assert fallback.published_date == "2025-01-17"
    assert fallback.snippet == " | ".join(
        [
            "Publisher: SIG-GR",
            "Catalogue: Plateforme luxembourgeoise",
            "Distributions: 1",
        ]
    )


@pytest.mark.asyncio
async def test_search_uses_requested_language(respx_mock) -> None:
    _mock(
        respx_mock,
        {
            "result": {
                "results": [
                    {
                        "id": "wetter",
                        "title": {"en": "Weather", "de": "Wetter"},
                        "description": {"en": "Weather data", "de": "Wetterdaten"},
                        "categories": [{"id": "ENVI", "label": {"de": "Umwelt"}}],
                        "resource": "http://data.europa.eu/88u/dataset/wetter",
                    },
                ],
            },
        },
    )

    result = await _provider().search(
        "wetter",
        SearchParams(num_results=5, language="de-DE"),
    )
    dataset = result.results[0]

    assert dataset.title == "Wetter"
    assert dataset.snippet.startswith("Wetterdaten")
    assert dataset.extra["categories"] == ["Umwelt"]


@pytest.mark.asyncio
async def test_search_skips_incomplete_and_malformed_entries(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("air", SearchParams(num_results=10))

    assert [r.title for r in result.results] == [
        "BelAQI Index - Belgian Air Quality Index",
        "Énergies renouvelables",
    ]
    assert [r.rank for r in result.results] == [1, 2]


@pytest.mark.asyncio
async def test_search_deduplicates_by_dataset_id(respx_mock) -> None:
    duplicate = {
        "id": "same-dataset",
        "title": {"en": "Same dataset"},
        "resource": "http://data.europa.eu/88u/dataset/same-dataset",
    }
    _mock(respx_mock, {"result": {"results": [duplicate, dict(duplicate)]}})

    result = await _provider().search("same", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["Same dataset"]


@pytest.mark.asyncio
async def test_search_builds_url_from_identifier_alone(respx_mock) -> None:
    _mock(
        respx_mock,
        {
            "result": {
                "results": [
                    {"id": "identifier-only", "title": {"en": "Identifier only"}},
                ],
            },
        },
    )

    result = await _provider().search("identifier", SearchParams(num_results=5))
    dataset = result.results[0]

    assert dataset.title == "Identifier only"
    assert dataset.url == (
        "https://data.europa.eu/data/datasets/identifier-only?locale=en"
    )
    assert dataset.snippet == ""
    assert dataset.published_date is None
    assert dataset.extra["publisher"] is None
    assert dataset.extra["distributions"] == 0
    assert dataset.extra["high_value_dataset"] is False


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("air", SearchParams(num_results=1))

    assert [r.title for r in result.results] == [
        "BelAQI Index - Belgian Air Quality Index",
    ]


@pytest.mark.asyncio
async def test_search_sends_query_params(respx_mock) -> None:
    route = _mock(respx_mock)

    await _provider().search("renewable energy", SearchParams(num_results=7))

    params = route.calls.last.request.url.params
    assert params["q"] == "renewable energy"
    assert params["limit"] == "7"
    assert params["page"] == "1"


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
        {"result": {"results": "nope"}},
    ):
        respx_mock.get(_SEARCH_URL).mock(
            return_value=respx.MockResponse(200, json=payload),
        )
        result = await _provider().search("air", SearchParams(num_results=5))
        assert result.results == []


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("air", SearchParams(num_results=5))
