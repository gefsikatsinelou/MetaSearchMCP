"""Unit tests for the Iconify vector-icon search provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.iconify import IconifyProvider

_SEARCH_URL = "https://api.iconify.design/search"

_PAYLOAD = {
    "icons": [
        "material-symbols:coffee",
        "mdi:coffee-outline",
        "ic:baseline-coffee",
    ],
    "total": 32,
    "limit": 32,
    "start": 0,
    "collections": {
        "material-symbols": {
            "name": "Material Symbols",
            "total": 15642,
            "author": {
                "name": "Google",
                "url": "https://github.com/google/material-design-icons",
            },
            "license": {
                "title": "Apache 2.0",
                "spdx": "Apache-2.0",
                "url": "https://github.com/google/material-design-icons/LICENSE",
            },
            "category": "Material",
            "tags": ["Has Padding"],
            "palette": False,
            "height": 24,
        },
        "mdi": {
            "name": "Material Design Icons",
            "total": 7447,
            "author": {"name": "Pictogrammers"},
            "license": {"title": "Apache 2.0", "spdx": "Apache-2.0"},
            "tags": ["Precise Shapes", "Has Padding", "Precise Shapes"],
            "palette": True,
        },
    },
    "request": {"query": "coffee", "limit": 32},
}


def _provider() -> IconifyProvider:
    """Return a fresh provider instance for each test."""
    return IconifyProvider()


def _mock(respx_mock, payload: object = _PAYLOAD):
    """Mock the Iconify search endpoint with *payload*."""
    return respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=payload),
    )


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "iconify"
    assert p.tags == ["web", "media", "image", "design"]
    assert "No API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "iconify" in registry
    assert registry["iconify"].tags == ["web", "media", "image", "design"]


def test_parse_builds_result_from_icon() -> None:
    result = _provider()._parse(_PAYLOAD, 10)

    assert [r.title for r in result.results] == [
        "material-symbols:coffee",
        "mdi:coffee-outline",
        "ic:baseline-coffee",
    ]
    icon = result.results[0]
    assert icon.url == "https://icon-sets.iconify.design/material-symbols/coffee/"
    assert icon.source == "iconify.design"
    assert icon.provider == "iconify"
    assert icon.rank == 1
    assert icon.published_date is None
    assert icon.snippet == (
        "Set: Material Symbols (material-symbols) | Author: Google | "
        "License: Apache 2.0 | Category: Material | Palette: no | "
        "SVG: https://api.iconify.design/material-symbols/coffee.svg"
    )
    assert icon.extra == {
        "identifier": "material-symbols:coffee",
        "prefix": "material-symbols",
        "name": "coffee",
        "collection": "Material Symbols",
        "collection_url": "https://github.com/google/material-design-icons",
        "author": "Google",
        "license": "Apache 2.0",
        "license_spdx": "Apache-2.0",
        "license_url": "https://github.com/google/material-design-icons/LICENSE",
        "category": "Material",
        "collection_tags": ["Has Padding"],
        "palette": False,
        "height": 24,
        "collection_size": 15642,
        "svg_url": "https://api.iconify.design/material-symbols/coffee.svg",
        "page_url": "https://icon-sets.iconify.design/material-symbols/coffee/",
        "total_results": 32,
    }


def test_parse_falls_back_when_collection_is_missing() -> None:
    result = _provider()._parse(
        {"icons": ["ic:baseline-coffee"], "total": 1},
        10,
    )
    icon = result.results[0]

    # The identifier supplies the set name when no metadata was returned.
    assert icon.snippet == (
        "Set: ic (ic) | Palette: no | "
        "SVG: https://api.iconify.design/ic/baseline-coffee.svg"
    )
    assert icon.extra["collection"] == "ic"
    assert icon.extra["author"] is None
    assert icon.extra["license"] is None
    assert icon.extra["category"] is None
    assert icon.extra["collection_tags"] == []
    assert icon.extra["palette"] is False
    assert icon.extra["height"] is None
    assert icon.extra["collection_size"] is None
    assert icon.extra["total_results"] == 1


def test_parse_uses_palette_and_deduplicates_set_tags() -> None:
    result = _provider()._parse(_PAYLOAD, 10)
    icon = result.results[1]

    assert icon.extra["palette"] is True
    assert icon.extra["collection_tags"] == ["Precise Shapes", "Has Padding"]
    assert icon.extra["license_url"] is None
    assert icon.extra["height"] is None
    assert icon.snippet.endswith(
        "SVG: https://api.iconify.design/mdi/coffee-outline.svg"
    )


def test_parse_skips_malformed_identifiers_and_duplicates() -> None:
    payload = {
        "icons": [
            "mdi:home",
            "mdi:home",
            "",
            "no-colon",
            ":missing-prefix",
            "missing-name:",
            None,
            42,
            {"icon": "mdi:home"},
            "mdi:home-outline",
        ],
        "total": 2,
    }
    result = _provider()._parse(payload, 10)

    assert [r.title for r in result.results] == ["mdi:home", "mdi:home-outline"]
    assert [r.rank for r in result.results] == [1, 2]


def test_parse_caps_results_and_handles_bad_totals() -> None:
    payload = {"icons": ["mdi:a", "mdi:b", "mdi:c"], "total": "many"}

    result = _provider()._parse(payload, 2)

    assert [r.title for r in result.results] == ["mdi:a", "mdi:b"]
    assert result.results[0].extra["total_results"] is None


def test_parse_handles_unexpected_payload_shapes() -> None:
    for payload in (["not", "a", "mapping"], {}, {"icons": "nope"}, None):
        assert _provider()._parse(payload, 5).results == []


@pytest.mark.asyncio
async def test_search_sends_query_params(respx_mock) -> None:
    route = _mock(respx_mock)

    await _provider().search("  coffee   mug ", SearchParams(num_results=4))

    params = route.calls.last.request.url.params
    assert params["query"] == "coffee mug"
    assert params["limit"] == "4"


@pytest.mark.asyncio
async def test_search_returns_parsed_results(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("coffee", SearchParams(num_results=3))

    assert [r.title for r in result.results] == [
        "material-symbols:coffee",
        "mdi:coffee-outline",
        "ic:baseline-coffee",
    ]


@pytest.mark.asyncio
async def test_search_truncates_to_requested_limit(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("coffee", SearchParams(num_results=1))

    assert [r.title for r in result.results] == ["material-symbols:coffee"]


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    route = _mock(respx_mock)

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("coffee", SearchParams(num_results=5))
