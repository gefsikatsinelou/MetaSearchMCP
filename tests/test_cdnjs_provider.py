"""Unit tests for the keyless cdnjs front-end library search provider."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.cdnjs import CdnjsProvider

_ENDPOINT = "https://api.cdnjs.com/libraries"


def _response(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a cdnjs search envelope around *results*."""
    return {"results": results, "total": len(results), "available": 1084}


_CHART: dict[str, Any] = _response(
    [
        {
            "name": "Chart.js",
            "latest": "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.min.js",
            "version": "4.4.0",
            "description": "Simple HTML5 charts using the canvas element.",
            "license": "MIT",
            "homepage": "https://www.chartjs.org",
            "repository": {
                "type": "git",
                "url": "https://github.com/chartjs/Chart.js.git",
            },
        },
        {
            "name": "chartist",
            "latest": "https://cdnjs.cloudflare.com/ajax/libs/chartist/0.11.4/chartist.min.js",
            "version": "0.11.4",
            "description": "Simple responsive charts",
            "license": "MIT",
            "repository": {
                "type": "git",
                "url": "https://github.com/gionkunz/chartist-js.git",
            },
        },
    ]
)


def test_cdnjs_name_tags_and_availability() -> None:
    p = CdnjsProvider()
    assert p.name == "cdnjs"
    assert p.tags == ["code", "developer", "web"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_cdnjs_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "cdnjs" in registry
    assert registry["cdnjs"].tags == ["code", "developer", "web"]


def test_cdnjs_parse_single_library() -> None:
    p = CdnjsProvider()
    result = p._parse(_CHART, limit=5)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Chart.js"
    assert r.url == "https://www.chartjs.org"
    assert r.source == "cdnjs"
    assert r.provider == "cdnjs"
    assert r.rank == 1
    assert r.published_date is None
    assert (
        r.snippet
        == "Simple HTML5 charts using the canvas element. | v4.4.0 | License: MIT"
    )
    assert r.extra["version"] == "4.4.0"
    assert r.extra["license"] == "MIT"
    assert r.extra["homepage"] == "https://www.chartjs.org"
    assert r.extra["repository"] == "https://github.com/chartjs/Chart.js.git"


def test_cdnjs_parse_falls_back_to_library_url_without_homepage() -> None:
    p = CdnjsProvider()
    r = p._parse(_CHART).results[1]

    assert r.title == "chartist"
    assert r.url == "https://cdnjs.com/libraries/chartist"
    assert r.extra["homepage"] is None
    assert r.extra["repository"] == "https://github.com/gionkunz/chartist-js.git"


def test_cdnjs_parse_preserves_order_and_ranks() -> None:
    p = CdnjsProvider()
    result = p._parse(_CHART)

    assert [r.title for r in result.results] == ["Chart.js", "chartist"]
    assert [r.rank for r in result.results] == [1, 2]


def test_cdnjs_parse_skips_unusable_libraries() -> None:
    p = CdnjsProvider()
    payload = _response(
        [
            {},
            {"name": ""},
            {"name": "  vue  ", "version": "3.4.0"},
        ]
    )
    results = p._parse(payload).results

    assert [r.title for r in results] == ["vue"]
    assert results[0].rank == 1
    assert results[0].snippet == "v3.4.0"


def test_cdnjs_parse_respects_limit() -> None:
    p = CdnjsProvider()
    assert len(p._parse(_CHART, limit=1).results) == 1
    assert len(p._parse(_CHART).results) == 2


def test_cdnjs_parse_empty_and_malformed() -> None:
    p = CdnjsProvider()
    assert p._parse({}).results == []
    assert p._parse(_response([])).results == []
    assert p._parse({"results": "nope"}).results == []
    assert p._parse({"results": []}).results == []
    assert p._parse([_CHART]).results == []
    assert p._parse("nope").results == []
    assert p._parse(None).results == []


def test_cdnjs_helpers() -> None:
    from metasearchmcp.providers.cdnjs import _clean

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _clean(42) == ""
    assert (
        CdnjsProvider._repository_url({"url": "https://x/y.git"}) == "https://x/y.git"
    )
    assert CdnjsProvider._repository_url({"url": ""}) == ""
    assert CdnjsProvider._repository_url("not-a-dict") == ""
    assert CdnjsProvider._repository_url(None) == ""


async def test_cdnjs_search_sends_expected_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_CHART)
    )

    result = await CdnjsProvider().search("chart", SearchParams(num_results=5))

    assert route.called
    request = route.calls[0].request
    assert request.url.params["search"] == "chart"
    assert request.url.params["limit"] == "5"
    assert "name" in request.url.params["fields"]
    assert [r.title for r in result.results] == ["Chart.js", "chartist"]


async def test_cdnjs_search_no_matches_returns_empty(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_response([]))
    )

    result = await CdnjsProvider().search("zzz", SearchParams())
    assert result.results == []


async def test_cdnjs_search_respects_result_limits(respx_mock) -> None:
    libraries = [{"name": f"lib{n}", "version": "1.0.0"} for n in range(1, 41)]
    respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_response(libraries))
    )

    provider = CdnjsProvider()
    provider._max_results = 1000
    result = await provider.search("lib", SearchParams(num_results=30))
    assert len(result.results) == 30

    provider._max_results = 1
    result = await provider.search("lib", SearchParams(num_results=30))
    assert len(result.results) == 1


async def test_cdnjs_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT)

    result = await CdnjsProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_cdnjs_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(500))

    with pytest.raises(httpx.HTTPStatusError):
        await CdnjsProvider().search("chart", SearchParams())
