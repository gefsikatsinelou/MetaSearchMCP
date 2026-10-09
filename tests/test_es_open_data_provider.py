"""Unit tests for the Spanish open data portal (datos.gob.es) provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.es_open_data import (
    EsOpenDataProvider,
    _formats,
    _iso_date,
    _last_segment,
    _localized,
    _theme_labels,
)

_SEARCH_URL = "https://datos.gob.es/apidata/catalog/dataset/title/vivienda"

_PAYLOAD = {
    "format": "linked-data-api",
    "version": "0.2",
    "result": {
        "itemsPerPage": 3,
        "page": 0,
        "startIndex": 1,
        "items": [
            {
                "_about": (
                    "https://datos.gob.es/catalogo/"
                    "l01281317-numero-de-viviendas-segun-tamano"
                ),
                "identifier": "172ca7e4-1e86-4b96-9096-ee0f3ca0e28b",
                "title": [
                    {"_value": "Housing count by size", "_lang": "en"},
                    {
                        "_value": "Número de viviendas según tamaño",
                        "_lang": "es",
                    },
                ],
                "description": [
                    {
                        "_value": (
                            "<p>Datos del <b>Censo</b> de Población y Viviendas.</p>"
                        ),
                        "_lang": "es",
                    },
                ],
                "keyword": [
                    {"_value": "censo", "_lang": "es"},
                    {"_value": "viviendas", "_lang": "es"},
                    {"_value": "censo", "_lang": "es"},
                ],
                "theme": "http://datos.gob.es/kos/sector-publico/sector/vivienda",
                "publisher": (
                    "http://datos.gob.es/recurso/sector-publico/org/Organismo/L01281317"
                ),
                "distribution": [
                    {
                        "accessURL": "https://example.org/data.csv",
                        "format": (
                            "http://publications.europa.eu/resource/"
                            "authority/file-type/CSV"
                        ),
                    },
                ],
                "issued": "lun, 22 dic 2025 15:30:56 GMT+0000",
                "modified": "mar, 13 ene 2026 13:56:59 GMT+0000",
            },
            {
                # No Spanish title -> falls back to the first available value.
                # A single distribution provided as a bare mapping.
                "_about": "https://datos.gob.es/catalogo/single-distribution",
                "identifier": "single-dist",
                "title": [
                    {"_value": "Single Distribution Dataset", "_lang": "en"},
                ],
                "description": "A description without markup.",
                "keyword": [],
                "theme": [
                    "http://datos.gob.es/kos/sector-publico/sector/medio-ambiente",
                ],
                "distribution": {
                    "format": (
                        "http://publications.europa.eu/resource/authority/file-type/PDF"
                    ),
                },
                "modified": "sáb, 01 jun 2024 08:00:00 GMT+0000",
            },
            {
                # Missing title -> skipped.
                "_about": "https://datos.gob.es/catalogo/no-title",
                "identifier": "no-title",
                "title": [],
            },
            {
                # Missing _about -> skipped.
                "identifier": "no-about",
                "title": [{"_value": "Orphan", "_lang": "es"}],
            },
        ],
    },
}

_EMPTY_PAYLOAD = {"result": {"items": [], "itemsPerPage": 50, "page": 0}}


def test_es_open_data_parse_basic():
    result = EsOpenDataProvider()._parse(_PAYLOAD, 50)

    assert len(result) == 2
    first = result[0]
    # Spanish title preferred over the English one.
    assert first.title == "Número de viviendas según tamaño"
    assert first.url == (
        "https://datos.gob.es/catalogo/l01281317-numero-de-viviendas-segun-tamano"
    )
    assert first.source == "datos.gob.es"
    assert first.provider == "es_open_data"
    assert first.rank == 1
    # HTML is stripped from the description.
    assert "Censo de Población y Viviendas" in first.snippet
    assert "<b>" not in first.snippet
    assert "Keywords: censo, viviendas" in first.snippet
    assert "Categories: vivienda" in first.snippet
    assert "Formats: CSV" in first.snippet
    assert "Publisher: L01281317" in first.snippet
    assert first.published_date == "2025-12-22"
    assert first.extra["identifier"] == "172ca7e4-1e86-4b96-9096-ee0f3ca0e28b"
    assert first.extra["keywords"] == ["censo", "viviendas"]
    assert first.extra["categories"] == ["vivienda"]
    assert first.extra["formats"] == ["CSV"]
    assert first.extra["published"] == "2025-12-22"
    assert first.extra["updated"] == "2026-01-13"


def test_es_open_data_parse_second_item_falls_back_to_modified():
    result = EsOpenDataProvider()._parse(_PAYLOAD, 50)

    second = result[1]
    assert second.title == "Single Distribution Dataset"
    assert second.rank == 2
    assert second.extra["formats"] == ["PDF"]
    assert second.extra["categories"] == ["medio-ambiente"]
    # No `issued` date -> published_date falls back to the modified date.
    assert second.published_date == "2024-06-01"
    assert second.extra["published"] is None
    assert second.extra["updated"] == "2024-06-01"


def test_es_open_data_parse_skips_incomplete_items():
    result = EsOpenDataProvider()._parse(_PAYLOAD, 50)
    urls = [r.url for r in result]
    assert "https://datos.gob.es/catalogo/no-title" not in urls
    assert all(r.title != "Orphan" for r in result)


def test_es_open_data_parse_respects_limit():
    result = EsOpenDataProvider()._parse(_PAYLOAD, 1)
    assert len(result) == 1
    assert result[0].rank == 1


def test_es_open_data_parse_dedupes_by_about():
    payload = {"result": {"items": [_PAYLOAD["result"]["items"][0]] * 2}}
    result = EsOpenDataProvider()._parse(payload, 50)
    assert len(result) == 1


def test_es_open_data_parse_empty_and_malformed():
    provider = EsOpenDataProvider()
    assert provider._parse(_EMPTY_PAYLOAD, 50) == []
    assert provider._parse({}, 50) == []
    assert provider._parse({"result": None}, 50) == []
    assert provider._parse({"result": {"items": None}}, 50) == []
    assert provider._parse([], 50) == []


def test_es_open_data_iso_date():
    assert _iso_date("lun, 22 dic 2025 15:30:56 GMT+0000") == "2025-12-22"
    assert _iso_date("mar, 13 ene 2026 13:56:59 GMT+0000") == "2026-01-13"
    assert _iso_date("sáb, 01 jun 2024 08:00:00 GMT+0000") == "2024-06-01"
    assert _iso_date(None) is None
    assert _iso_date("") is None
    assert _iso_date("no date here") is None


def test_es_open_data_localized_prefers_spanish():
    values = [
        {"_value": "English", "_lang": "en"},
        {"_value": "Español", "_lang": "es"},
    ]
    assert _localized(values) == "Español"
    assert _localized([{"_value": "Only", "_lang": "en"}]) == "Only"
    assert _localized("plain string") == "plain string"
    assert _localized({"_value": "Single", "_lang": "es"}) == "Single"
    assert _localized(None) == ""
    assert _localized([]) == ""


def test_es_open_data_last_segment():
    assert _last_segment("http://x/y/CSV") == "CSV"
    assert _last_segment("http://x/y/L01281317") == "L01281317"
    assert _last_segment("bare") == "bare"
    assert _last_segment(None) == ""


def test_es_open_data_formats_and_theme():
    assert _formats(
        [{"format": "http://x/CSV"}, {"format": "http://x/CSV"}, {"format": "PDF"}],
        4,
    ) == ["CSV", "PDF"]
    assert _formats({"format": "http://x/JSON"}, 4) == ["JSON"]
    assert _formats(None, 4) == []
    assert _theme_labels(
        ["http://datos.gob.es/kos/sector-publico/sector/vivienda"],
        5,
    ) == ["vivienda"]
    assert _theme_labels("http://x/transport", 5) == ["transport"]
    assert _theme_labels(None, 5) == []


def test_es_open_data_is_available_and_registered():
    provider = EsOpenDataProvider()
    assert provider.is_available() is True
    assert provider.name == "es_open_data"
    assert {"web", "gov", "data", "knowledge"}.issubset(set(provider.tags))

    from metasearchmcp.catalog import build_provider_catalog

    catalog = build_provider_catalog()
    assert "es_open_data" in catalog


@pytest.mark.asyncio
async def test_es_open_data_search_builds_query(respx_mock):
    respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=_PAYLOAD),
    )

    provider = EsOpenDataProvider()
    result = await provider.search("vivienda", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "es_open_data"
    request = respx_mock.calls.last.request
    assert request.url.params["_pageSize"] == "5"
    assert request.url.params["_page"] == "0"


@pytest.mark.asyncio
async def test_es_open_data_search_blank_query_skips_request(respx_mock):
    provider = EsOpenDataProvider()
    result = await provider.search("   ", SearchParams(num_results=5))
    assert result.results == []
    assert respx_mock.calls.call_count == 0


@pytest.mark.asyncio
async def test_es_open_data_search_raises_on_error(respx_mock):
    respx_mock.get(_SEARCH_URL).mock(return_value=respx.MockResponse(500))

    provider = EsOpenDataProvider()
    with pytest.raises(HTTPStatusError):
        await provider.search("vivienda", SearchParams(num_results=5))
