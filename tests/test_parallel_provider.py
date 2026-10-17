"""Parallel caller tests using the real MCP session and HTTP transport."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from metasearchmcp.config import Settings, get_settings
from metasearchmcp.contracts import SearchOptions
from metasearchmcp.providers.base import API_USER_AGENT, MAX_SNIPPET_LENGTH

MCP_URL = "https://search.parallel.ai/mcp"


@pytest.fixture
def parallel_settings(monkeypatch):
    # Isolate local .env and saved user credentials as well as environment keys.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("PARALLEL_ENABLED", "true")
    monkeypatch.setenv("ENABLED_PROVIDERS", "parallel")
    monkeypatch.setenv("CACHE_ENABLED", "false")
    monkeypatch.setenv("DEFAULT_TIMEOUT", "2")
    monkeypatch.setenv("AGGREGATOR_TIMEOUT", "2")
    monkeypatch.setenv("MAX_RESULTS_PER_PROVIDER", "10")
    monkeypatch.setenv("PARALLEL_API_KEY", "must-not-be-sent")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def mcp_endpoint(respx_mock):
    state = {
        "payload": {
            "results": [
                {
                    "title": "Asyncio tasks",
                    "url": "https://docs.python.org/3/library/asyncio-task.html",
                    "excerpts": ["Task cancellation documentation.", "More context."],
                    "publish_date": "2026-07-01",
                },
                {"title": None, "url": "https://example.com", "excerpts": ["x" * 500]},
            ]
        },
        "text_only": False,
        "raw_text": None,
        "error": False,
        "block": False,
        "started": asyncio.Event(),
        "cancelled": asyncio.Event(),
        "calls": [],
    }

    async def handle(request):
        assert str(request.url) == MCP_URL
        assert request.headers["user-agent"] == API_USER_AGENT
        assert "authorization" not in request.headers
        if request.method == "GET":
            return httpx.Response(405)
        message = json.loads(request.content)
        state["calls"].append(message)
        method = message["method"]
        if method.startswith("notifications/"):
            return httpx.Response(202)
        if method == "initialize":
            result = {
                "protocolVersion": message["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "parallel-fixture", "version": "1.0"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "web_search",
                        "inputSchema": {"type": "object"},
                    }
                ]
            }
        else:
            assert method == "tools/call"
            state["started"].set()
            if state["block"]:
                try:
                    await asyncio.Event().wait()
                finally:
                    state["cancelled"].set()
            text = state["raw_text"] or (
                "Anonymous quota exceeded"
                if state["error"]
                else json.dumps(state["payload"])
            )
            result = {
                "content": [{"type": "text", "text": text}],
                "isError": state["error"],
            }
            if not state["text_only"] and not state["error"]:
                result["structuredContent"] = state["payload"]
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": message["id"], "result": result}
        )

    respx_mock.route(url=MCP_URL).mock(side_effect=handle)
    return state


def test_parallel_is_opt_in_and_respects_allowlist(parallel_settings, monkeypatch):
    from metasearchmcp.catalog import build_provider_catalog, pick_first_provider

    monkeypatch.setenv("PARALLEL_ENABLED", "false")
    monkeypatch.setenv("ENABLED_PROVIDERS", "")
    get_settings.cache_clear()
    original = build_provider_catalog()
    assert "parallel" not in original

    monkeypatch.setenv("PARALLEL_ENABLED", "true")
    get_settings.cache_clear()
    enabled = build_provider_catalog()
    assert [name for name in enabled if name != "parallel"] == list(original)
    assert list(pick_first_provider(enabled)) == list(pick_first_provider(original))

    monkeypatch.setenv("ENABLED_PROVIDERS", "wikipedia")
    get_settings.cache_clear()
    assert list(build_provider_catalog()) == ["wikipedia"]
    monkeypatch.setenv("ENABLED_PROVIDERS", "parallel")
    get_settings.cache_clear()
    assert list(build_provider_catalog()) == ["parallel"]
    monkeypatch.setenv("PARALLEL_ENABLED", "false")
    get_settings.cache_clear()
    assert build_provider_catalog() == {}


@pytest.mark.parametrize("text_only", [False, True])
async def test_mcp_search_selection_normalizes_results(
    parallel_settings, mcp_endpoint, monkeypatch, text_only
):
    from metasearchmcp import broker
    from metasearchmcp.catalog import build_provider_catalog

    mcp_endpoint["text_only"] = text_only
    monkeypatch.setattr(broker, "_catalog", build_provider_catalog())
    response = await broker.call_tool(
        "search_web",
        {
            "query": "Python asyncio task cancellation",
            "providers": ["parallel"],
            "num_results": 2,
        },
    )
    report = json.loads(response[0].text)
    assert not report["errors"]
    first, second = report["results"]
    assert first["title"] == "Asyncio tasks"
    assert first["source"] == "docs.python.org"
    assert first["snippet"] == "Task cancellation documentation.\n\nMore context."
    assert first["published_date"] == "2026-07-01"
    assert first["provider"] == "parallel"
    assert first["rank"] == 1
    assert (
        first["extra"]["excerpts"] == mcp_endpoint["payload"]["results"][0]["excerpts"]
    )
    assert second["title"] == second["url"]
    assert second["rank"] == 2
    assert len(second["snippet"]) == MAX_SNIPPET_LENGTH
    assert report["providers"][0]["success"] is True
    call = next(m for m in mcp_endpoint["calls"] if m["method"] == "tools/call")
    assert call["params"]["name"] == "web_search"
    assert call["params"]["arguments"] == {
        "objective": "Python asyncio task cancellation",
        "search_queries": ["Python asyncio task cancellation"],
    }


async def test_http_selection_and_result_caps(parallel_settings, mcp_endpoint):
    from fastapi import FastAPI

    from metasearchmcp.api import routes
    from metasearchmcp.catalog import build_provider_catalog

    parallel_settings.max_results_per_provider = 1
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes._get_registry] = build_provider_catalog
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/search",
            json={
                "query": "asyncio",
                "providers": ["parallel"],
                "params": {"num_results": 5},
            },
        )
        assert response.status_code == 200
        assert len(response.json()["results"]) == 1
        parallel_settings.max_results_per_provider = 10
        response = await client.post(
            "/search",
            json={
                "query": "asyncio",
                "providers": ["parallel"],
                "params": {"num_results": 1},
            },
        )
        assert len(response.json()["results"]) == 1
        response = await client.post(
            "/search",
            json={
                "query": "asyncio",
                "providers": ["parallel"],
                "params": {"max_total_results": 1},
            },
        )
        assert len(response.json()["results"]) == 1


@pytest.mark.parametrize("failure", ["error", "invalid_json", "invalid_shape"])
async def test_failures_are_provider_errors(parallel_settings, mcp_endpoint, failure):
    from metasearchmcp.catalog import build_provider_catalog
    from metasearchmcp.orchestrator import run_search_plan

    if failure == "error":
        mcp_endpoint["error"] = True
    elif failure == "invalid_json":
        mcp_endpoint["text_only"] = True
        mcp_endpoint["raw_text"] = "{not-json"
    else:
        mcp_endpoint["payload"] = {"unexpected": []}
    report = await run_search_plan("asyncio", list(build_provider_catalog().values()))
    assert report.results == []
    assert report.errors
    assert report.providers[0].success is False
    if failure == "error":
        assert "Anonymous quota exceeded" in report.errors[0]


async def test_timeout_cancels_http_request(parallel_settings, mcp_endpoint):
    from metasearchmcp.catalog import build_provider_catalog
    from metasearchmcp.orchestrator import run_search_plan

    parallel_settings.default_timeout = 0.1
    mcp_endpoint["block"] = True
    report = await run_search_plan("asyncio", list(build_provider_catalog().values()))
    assert report.providers[0].success is False
    assert "timeout" in report.errors[0].lower()
    assert mcp_endpoint["cancelled"].is_set()


async def test_caller_cancellation_closes_http_request(parallel_settings, mcp_endpoint):
    from metasearchmcp.catalog import build_provider_catalog

    mcp_endpoint["block"] = True
    provider = build_provider_catalog()["parallel"]
    task = asyncio.create_task(provider.search("asyncio", SearchOptions()))
    await asyncio.wait_for(mcp_endpoint["started"].wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert mcp_endpoint["cancelled"].is_set()
