"""Unit tests for the PyPI package lookup provider."""

from __future__ import annotations

import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.pypi import PyPIProvider

_FASTAPI_INFO: dict[str, object] = {
    "name": "fastapi",
    "version": "0.111.0",
    "summary": "FastAPI framework, high performance",
    "keywords": "web, framework, api",
    "author": "Sebastián Ramírez",
    "license": "MIT",
    "requires_python": ">=3.8",
    "home_page": "https://fastapi.tiangolo.com",
    "package_url": "https://pypi.org/project/fastapi/",
}


def _pypi_response(info: dict[str, object] | None = None) -> dict[str, object]:
    return {"info": info or _FASTAPI_INFO}


def test_pypi_name_and_tags():
    p = PyPIProvider()
    assert p.name == "pypi"
    assert "code" in p.tags


def test_pypi_build_candidates():
    assert PyPIProvider._build_candidates("fastapi") == ["fastapi"]
    # space-separated tokens become candidates after the slug
    candidates = PyPIProvider._build_candidates("pydantic v2")
    assert candidates[0] == "pydantic-v2"
    assert "pydantic" in candidates
    assert "v2" in candidates


def test_pypi_build_snippet():
    info = dict(_FASTAPI_INFO)
    snippet = PyPIProvider._build_snippet(info)
    assert "FastAPI framework" in snippet
    assert "v0.111.0" in snippet
    assert "Keywords: web, framework, api" in snippet


def test_pypi_build_snippet_empty_keywords():
    info = dict(_FASTAPI_INFO)
    info["keywords"] = ""
    snippet = PyPIProvider._build_snippet(info)
    assert "Keywords" not in snippet
    assert "FastAPI framework" in snippet


@pytest.mark.asyncio
async def test_pypi_fetch_package_info_ok(respx_mock):
    respx_mock.get("https://pypi.org/pypi/fastapi/json").mock(
        return_value=respx.MockResponse(200, json=_pypi_response()),
    )
    p = PyPIProvider()
    data = await p._fetch_package_info(p._client(), "fastapi")
    assert data is not None
    assert data["info"]["name"] == "fastapi"


@pytest.mark.asyncio
async def test_pypi_fetch_package_info_not_found(respx_mock):
    respx_mock.get("https://pypi.org/pypi/nonexistent-pkg/json").mock(
        return_value=respx.MockResponse(404),
    )
    p = PyPIProvider()
    assert await p._fetch_package_info(p._client(), "nonexistent-pkg") is None


@pytest.mark.asyncio
async def test_pypi_fetch_package_info_http_error(respx_mock):
    respx_mock.get("https://pypi.org/pypi/broken/json").mock(
        return_value=respx.MockResponse(500),
    )
    p = PyPIProvider()
    assert await p._fetch_package_info(p._client(), "broken") is None


@pytest.mark.asyncio
async def test_pypi_fetch_package_info_invalid_json(respx_mock):
    respx_mock.get("https://pypi.org/pypi/bad/json").mock(
        return_value=respx.MockResponse(200, text="not json"),
    )
    p = PyPIProvider()
    assert await p._fetch_package_info(p._client(), "bad") is None


@pytest.mark.asyncio
async def test_pypi_search_finds_package(respx_mock):
    respx_mock.get("https://pypi.org/pypi/fastapi/json").mock(
        return_value=respx.MockResponse(200, json=_pypi_response()),
    )
    p = PyPIProvider()
    result = await p.search("fastapi", SearchParams(num_results=5))

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "fastapi"
    assert r.url == "https://pypi.org/project/fastapi/"
    assert r.provider == "pypi"
    assert r.rank == 1
    assert r.source == "pypi.org"
    assert r.extra["version"] == "0.111.0"
    assert r.extra["license"] == "MIT"
    assert "FastAPI framework" in r.snippet


@pytest.mark.asyncio
async def test_pypi_search_missing_package_yields_no_results(respx_mock):
    respx_mock.get("https://pypi.org/pypi/definitely-not-a-pkg/json").mock(
        return_value=respx.MockResponse(404),
    )
    p = PyPIProvider()
    result = await p.search("definitely-not-a-pkg", SearchParams(num_results=5))
    assert result.results == []


@pytest.mark.asyncio
async def test_pypi_search_respects_max_results(respx_mock):
    """Once the result cap is reached, remaining candidates are not fetched."""
    respx_mock.get("https://pypi.org/pypi/aaa-bbb/json").mock(
        return_value=respx.MockResponse(200, json=_pypi_response()),
    )
    respx_mock.get("https://pypi.org/pypi/aaa/json").mock(
        return_value=respx.MockResponse(200, json=_pypi_response()),
    )
    respx_mock.get("https://pypi.org/pypi/bbb/json").mock(
        return_value=respx.MockResponse(200, json=_pypi_response()),
    )
    p = PyPIProvider()
    result = await p.search("aaa bbb", SearchParams(num_results=1))

    assert len(result.results) == 1
    # The first candidate (slug "aaa-bbb") matches and fills the cap, so the
    # remaining token candidates are never fetched.
    assert respx_mock.calls.call_count == 1
