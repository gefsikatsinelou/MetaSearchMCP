"""Tests for the DuckDuckGo-backed /search/suggest endpoint and helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from metasearchmcp.suggest import fetch_suggestions

_AC_URL = "https://duckduckgo.com/ac/"

# DuckDuckGo autocomplete returns ["query", ["suggestion", ...]].
_SAMPLE = ["python", ["python", "python download", "python compiler", "python 3"]]

_EMPTY = ["python", []]


@pytest.mark.asyncio
async def test_fetch_suggestions_parses_response(respx_mock):
    respx_mock.get(_AC_URL).mock(return_value=respx.MockResponse(200, json=_SAMPLE))

    suggestions = await fetch_suggestions("python")

    assert suggestions == ["python", "python download", "python compiler", "python 3"]


@pytest.mark.asyncio
async def test_fetch_suggestions_respects_limit(respx_mock):
    respx_mock.get(_AC_URL).mock(return_value=respx.MockResponse(200, json=_SAMPLE))

    suggestions = await fetch_suggestions("python", limit=2)

    assert suggestions == ["python", "python download"]


@pytest.mark.asyncio
async def test_fetch_suggestions_empty_list(respx_mock):
    respx_mock.get(_AC_URL).mock(return_value=respx.MockResponse(200, json=_EMPTY))

    assert await fetch_suggestions("python") == []


@pytest.mark.asyncio
async def test_fetch_suggestions_http_error_returns_empty(respx_mock):
    respx_mock.get(_AC_URL).mock(return_value=respx.MockResponse(500))

    assert await fetch_suggestions("python") == []


@pytest.mark.asyncio
async def test_fetch_suggestions_network_error_returns_empty(respx_mock):
    respx_mock.get(_AC_URL).mock(side_effect=httpx.ConnectError("boom"))

    assert await fetch_suggestions("python") == []


@pytest.mark.asyncio
async def test_fetch_suggestions_malformed_json_returns_empty(respx_mock):
    respx_mock.get(_AC_URL).mock(return_value=respx.MockResponse(200, text="not json"))

    assert await fetch_suggestions("python") == []


def test_suggest_route_returns_suggestions(client, respx_mock):
    respx_mock.get(_AC_URL).mock(return_value=respx.MockResponse(200, json=_SAMPLE))

    resp = client.get("/search/suggest", params={"q": "python", "limit": 3})

    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "python"
    assert data["count"] == 3
    assert data["source"] == "duckduckgo"
    assert data["suggestions"][:3] == ["python", "python download", "python compiler"]


def test_suggest_route_validation(client):
    resp = client.get("/search/suggest", params={"q": ""})
    assert resp.status_code == 422

    resp = client.get("/search/suggest", params={"q": "x", "limit": 0})
    assert resp.status_code == 422


def test_suggest_route_empty_result(client, respx_mock):
    respx_mock.get(_AC_URL).mock(return_value=respx.MockResponse(200, json=_EMPTY))

    resp = client.get("/search/suggest", params={"q": "zzzz"})

    assert resp.status_code == 200
    assert resp.json()["suggestions"] == []


@pytest.fixture
def client():
    from fastapi import FastAPI

    from metasearchmcp.api import routes

    app = FastAPI()
    app.include_router(routes.router)

    catalog = {
        "duckduckgo": _make_provider("duckduckgo", ["web"], "DuckDuckGo"),
    }
    with patch.object(routes, "_catalog", catalog), TestClient(app) as c:
        yield c


def _make_provider(name: str, tags: list[str], description: str = "") -> MagicMock:
    provider = MagicMock()
    provider.name = name
    provider.tags = tags
    provider.description = description
    provider.is_available.return_value = True
    return provider
