"""Tests for broker dispatch_tool (search_finance, search_code) and /providers route."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from metasearchmcp.contracts import ProviderPayload, SearchHit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(name: str, tags: list[str], description: str = "") -> MagicMock:
    provider = MagicMock()
    provider.name = name
    provider.tags = tags
    provider.description = description
    provider.is_available.return_value = True

    async def _search(query, params):
        return ProviderPayload(
            results=[
                SearchHit(title="T", url=f"https://{name}.example.com", provider=name),
            ],
        )

    provider.search = _search
    return provider


def _fake_catalog() -> dict:
    return {
        "yahoo_finance": _make_provider(
            "yahoo_finance",
            ["web", "finance"],
            "Yahoo Finance",
        ),
        "alpha_vantage": _make_provider(
            "alpha_vantage",
            ["web", "finance"],
            "Alpha Vantage",
        ),
        "github": _make_provider("github", ["web", "code", "developer"], "GitHub"),
        "npm": _make_provider("npm", ["web", "code", "developer", "packages"], "npm"),
        "bing": _make_provider("bing", ["web"], "Bing"),
    }


# ---------------------------------------------------------------------------
# broker.dispatch_tool tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_search_finance_returns_results():
    from metasearchmcp import broker

    catalog = _fake_catalog()
    with patch.object(broker, "_catalog", catalog):
        result = await broker.dispatch_tool("search_finance", {"query": "AAPL"})

    assert "results" in result
    providers_hit = {r["provider"] for r in result["results"]}
    assert providers_hit <= {"yahoo_finance", "alpha_vantage"}


@pytest.mark.asyncio
async def test_dispatch_search_finance_no_finance_providers():
    from metasearchmcp import broker

    catalog = {k: v for k, v in _fake_catalog().items() if "finance" not in v.tags}
    with patch.object(broker, "_catalog", catalog):
        result = await broker.dispatch_tool("search_finance", {"query": "AAPL"})

    assert "error" in result


@pytest.mark.asyncio
async def test_dispatch_search_code_returns_results():
    from metasearchmcp import broker

    catalog = _fake_catalog()
    with patch.object(broker, "_catalog", catalog):
        result = await broker.dispatch_tool("search_code", {"query": "async rust"})

    assert "results" in result
    providers_hit = {r["provider"] for r in result["results"]}
    assert providers_hit <= {"github", "npm"}


@pytest.mark.asyncio
async def test_dispatch_search_code_no_code_providers():
    from metasearchmcp import broker

    catalog = {"bing": _fake_catalog()["bing"]}
    with patch.object(broker, "_catalog", catalog):
        result = await broker.dispatch_tool("search_code", {"query": "async rust"})

    assert "error" in result


@pytest.mark.asyncio
async def test_dispatch_compare_engines_fallback_to_all():
    """compare_engines with empty providers list should fall back to full catalog."""
    from metasearchmcp import broker

    catalog = _fake_catalog()
    with patch.object(broker, "_catalog", catalog):
        result = await broker.dispatch_tool(
            "compare_engines",
            {"query": "test", "providers": []},
        )

    assert "engines" in result
    assert len(result["engines"]) == len(catalog)


@pytest.mark.asyncio
async def test_dispatch_unknown_tool():
    from metasearchmcp import broker

    result = await broker.dispatch_tool("nonexistent_tool", {"query": "x"})
    assert "error" in result


@pytest.mark.asyncio
async def test_dispatch_search_google_prefers_direct_google_provider():
    from metasearchmcp import broker

    catalog = {
        "google": _make_provider("google", ["google", "web"], "Google"),
        "google_serpbase": _make_provider(
            "google_serpbase",
            ["google", "web"],
            "SerpBase",
        ),
    }
    with patch.object(broker, "_catalog", catalog):
        result = await broker.dispatch_tool("search_google", {"query": "fastapi"})

    assert "results" in result
    providers_hit = {r["provider"] for r in result["results"]}
    assert providers_hit == {"google"}


@pytest.mark.asyncio
async def test_dispatch_search_google_can_select_direct_google_explicitly():
    from metasearchmcp import broker

    catalog = {
        "google": _make_provider("google", ["google", "web"], "Google"),
        "google_serper": _make_provider("google_serper", ["google", "web"], "Serper"),
    }
    with patch.object(broker, "_catalog", catalog):
        result = await broker.dispatch_tool(
            "search_google",
            {"query": "fastapi", "provider": "google"},
        )

    assert "results" in result
    providers_hit = {r["provider"] for r in result["results"]}
    assert providers_hit == {"google"}


def test_search_google_route_prefers_first_available_provider(client):
    from fastapi import FastAPI

    from metasearchmcp.api import routes

    catalog = {
        "google": _make_provider("google", ["google", "web"], "Google"),
        "google_serpbase": _make_provider(
            "google_serpbase",
            ["google", "web"],
            "SerpBase",
        ),
    }

    app = FastAPI()
    app.include_router(routes.router)

    with patch.object(routes, "_catalog", catalog), TestClient(app) as test_client:
        resp = test_client.post("/search/google", json={"query": "fastapi"})

    assert resp.status_code == 200
    data = resp.json()
    providers_hit = {r["provider"] for r in data["results"]}
    assert providers_hit == {"google"}


# ---------------------------------------------------------------------------
# /providers route tests
# ---------------------------------------------------------------------------


def _make_app_with_catalog(catalog: dict):
    """Return a FastAPI TestClient with a patched provider catalog."""
    from fastapi import FastAPI

    from metasearchmcp.api import routes

    app = FastAPI()
    app.include_router(routes.router)

    with patch.object(routes, "_catalog", catalog):
        client = TestClient(app)
        yield client


@pytest.fixture()
def client():
    from fastapi import FastAPI

    from metasearchmcp.api import routes

    app = FastAPI()
    app.include_router(routes.router)

    catalog = _fake_catalog()
    with patch.object(routes, "_catalog", catalog), TestClient(app) as c:
        yield c


def test_providers_list_all(client):
    resp = client.get("/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert "available" in data
    assert data["count"] == 5
    assert "tag_groups" in data


def test_providers_has_description(client):
    resp = client.get("/providers")
    data = resp.json()
    for p in data["available"]:
        assert "description" in p
        assert isinstance(p["description"], str)


def test_providers_tag_groups_structure(client):
    resp = client.get("/providers")
    data = resp.json()
    tg = data["tag_groups"]
    assert "finance" in tg
    assert "yahoo_finance" in tg["finance"]
    assert "code" in tg
    assert "github" in tg["code"]


def test_providers_filter_by_tag(client):
    resp = client.get("/providers?tag=finance")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    names = {p["name"] for p in data["available"]}
    assert names == {"yahoo_finance", "alpha_vantage"}


def test_providers_filter_by_code_tag(client):
    resp = client.get("/providers?tag=code")
    data = resp.json()
    names = {p["name"] for p in data["available"]}
    assert names == {"github", "npm"}


def test_providers_filter_by_all_tags(client):
    resp = client.get("/providers?tag=web&tag=finance&tag_match=all")
    assert resp.status_code == 200
    data = resp.json()
    names = {p["name"] for p in data["available"]}
    assert names == {"yahoo_finance", "alpha_vantage"}
    assert data["filters"] == {"tags": ["web", "finance"], "tag_match": "all"}


def test_providers_filters_normalize_tag_input(client):
    resp = client.get(
        "/providers?tag=%20Code%20&tag=%20PACKAGES%20&tag=code&tag_match=all",
    )
    assert resp.status_code == 200
    data = resp.json()
    names = {p["name"] for p in data["available"]}
    assert names == {"npm"}


@pytest.mark.asyncio
async def test_dispatch_search_web_supports_all_tag_matching():
    from metasearchmcp import broker

    catalog = _fake_catalog()
    with patch.object(broker, "_catalog", catalog):
        result = await broker.dispatch_tool(
            "search_web",
            {
                "query": "npm package",
                "tags": ["code", "packages"],
                "tag_match": "all",
            },
        )

    assert "results" in result
    providers_hit = {r["provider"] for r in result["results"]}
    assert providers_hit == {"npm"}


@pytest.mark.asyncio
async def test_dispatch_search_web_normalizes_provider_and_tag_filters():
    from metasearchmcp import broker

    catalog = _fake_catalog()
    with patch.object(broker, "_catalog", catalog):
        result = await broker.dispatch_tool(
            "search_web",
            {
                "query": "npm package",
                "providers": [" NPM ", "npm"],
                "tags": [" Code ", "PACKAGES"],
                "tag_match": "all",
            },
        )

    assert "results" in result
    providers_hit = {r["provider"] for r in result["results"]}
    assert providers_hit == {"npm"}


@pytest.mark.asyncio
async def test_dispatch_search_web_passes_safe_search():
    from metasearchmcp import broker
    from metasearchmcp.orchestrator import run_search_plan

    captured = {}
    original_run_search_plan = run_search_plan

    async def _capture_run_search_plan(query, providers, options):
        captured["options"] = options
        return await original_run_search_plan(query, providers, options)

    catalog = _fake_catalog()
    with patch.object(broker, "_catalog", catalog), patch.object(
        broker, "run_search_plan", _capture_run_search_plan
    ):
        result = await broker.dispatch_tool(
            "search_web",
            {
                "query": "npm package",
                "safe_search": False,
            },
        )

    assert "results" in result
    assert captured["options"].safe_search is False


@pytest.mark.asyncio
async def test_dispatch_search_google_passes_safe_search():
    from metasearchmcp import broker
    from metasearchmcp.orchestrator import run_search_plan

    captured = {}
    original_run_search_plan = run_search_plan

    async def _capture_run_search_plan(query, providers, options):
        captured["options"] = options
        return await original_run_search_plan(query, providers, options)

    catalog = {
        "google_serpbase": _make_provider(
            "google_serpbase",
            ["google", "web"],
            "SerpBase",
        ),
    }
    with patch.object(broker, "_catalog", catalog), patch.object(
        broker, "run_search_plan", _capture_run_search_plan
    ):
        result = await broker.dispatch_tool(
            "search_google",
            {
                "query": "fastapi",
                "safe_search": False,
            },
        )

    assert "results" in result
    assert captured["options"].safe_search is False


# ---------------------------------------------------------------------------
# provider description field tests
# ---------------------------------------------------------------------------


def test_all_providers_have_description():
    """Every instantiated provider should expose a non-empty description."""
    from metasearchmcp.catalog import build_provider_catalog

    catalog = build_provider_catalog()
    missing = [name for name, p in catalog.items() if not p.description]
    assert missing == [], f"Providers missing description: {missing}"
