"""Unit tests for the Keenable Search provider."""

from __future__ import annotations

import json

import pytest
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.keenable import KeenableProvider


def _payload() -> dict:
    """A representative Keenable Search API response."""
    return {
        "results": [
            {
                "title": "FastAPI",
                "url": "https://fastapi.tiangolo.com/",
                "description": "FastAPI is a modern, fast web framework for Python.",
                "snippet": "Long page excerpt.",
            },
            {
                "title": "FastAPI on GitHub",
                "url": "https://github.com/fastapi/fastapi",
                "snippet": "x" * 900,
            },
            {"title": "No URL", "description": "dropped"},
        ],
    }


def test_parse_prefers_description_then_truncated_snippet() -> None:
    result = KeenableProvider()._parse(_payload())

    assert [r.url for r in result.results] == [
        "https://fastapi.tiangolo.com/",
        "https://github.com/fastapi/fastapi",
    ]
    assert result.results[0].snippet.startswith("FastAPI is a modern")
    assert result.results[1].snippet == "x" * 500
    assert [r.rank for r in result.results] == [1, 2]
    assert all(r.provider == "keenable" for r in result.results)


def test_parse_empty() -> None:
    assert KeenableProvider()._parse({}).results == []
    assert KeenableProvider()._parse({"results": None}).results == []


def test_is_available_gated_on_api_key(monkeypatch) -> None:
    import metasearchmcp.config as cfg

    monkeypatch.setenv("KEENABLE_API_KEY", "")
    cfg.get_settings.cache_clear()
    assert KeenableProvider().is_available() is False

    monkeypatch.setenv("KEENABLE_API_KEY", "test-key")
    cfg.get_settings.cache_clear()
    assert KeenableProvider().is_available() is True
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_search_posts_query_with_api_key(respx_mock, monkeypatch) -> None:
    import respx

    import metasearchmcp.config as cfg

    monkeypatch.setenv("KEENABLE_API_KEY", "test-key")
    cfg.get_settings.cache_clear()
    route = respx_mock.post("https://api.keenable.ai/v1/search").mock(
        return_value=respx.MockResponse(200, json=_payload()),
    )

    result = await KeenableProvider().search("fastapi", SearchParams(num_results=5))
    cfg.get_settings.cache_clear()

    request = route.calls.last.request
    assert request.headers["X-API-Key"] == "test-key"
    assert json.loads(request.content) == {"query": "fastapi", "max_results": 5}
    assert len(result.results) == 2


@pytest.mark.asyncio
async def test_search_raises_on_http_error(respx_mock) -> None:
    import respx

    respx_mock.post("https://api.keenable.ai/v1/search").mock(
        return_value=respx.MockResponse(401, json={"error": "unauthorized"}),
    )
    with pytest.raises(HTTPStatusError):
        await KeenableProvider().search("fastapi", SearchParams(num_results=5))
