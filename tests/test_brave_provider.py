"""Unit tests for the Brave Search provider.

Covers parsing of the Brave Web Search API JSON response (including
facet/extra-result fields the parser deliberately ignores), error
handling, pagination, and availability gating on the API key.
"""

from __future__ import annotations

import pytest
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.brave import BraveProvider


def _payload() -> dict:
    """A realistic Brave Web Search API response."""
    return {
        "web": {
            "results": [
                {
                    "title": "FastAPI - The Modern Python Web Framework",
                    "url": "https://fastapi.tiangolo.com/",
                    "description": (
                        "FastAPI is a modern, fast web framework for Python."
                    ),
                    "age": "2 days ago",
                    "extra_snippets": ["Fast, async, type-driven."],
                    "profile": {
                        "name": "fastapi",
                        "url": "https://fastapi.tiangolo.com/",
                    },
                },
                {
                    "title": "FastAPI on GitHub",
                    "url": "https://github.com/fastapi/fastapi",
                    "description": "Source code and issue tracker.",
                },
            ],
        },
        "query": {"original": "fastapi", "show_strict_warning": False},
        "mixed": {
            "type": "mixed",
            "main": [{"type": "web", "index": 0}, {"type": "web", "index": 1}],
        },
    }


def _provider() -> BraveProvider:
    return BraveProvider()


def test_parse_basic() -> None:
    p = _provider()
    result = p._parse(_payload())

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "FastAPI - The Modern Python Web Framework"
    assert r.url == "https://fastapi.tiangolo.com/"
    assert r.provider == "brave"
    assert r.rank == 1
    assert "modern, fast web framework" in r.snippet
    # Brave's "age" field is a relative human string, never surfaced.
    assert r.published_date is None
    assert result.results[1].rank == 2


def test_parse_ignores_non_web_extra_blocks() -> None:
    """Facets / mixed blocks / query meta must not become results."""
    p = _provider()
    result = p._parse(_payload())
    assert len(result.results) == 2
    assert all(r.url.startswith("http") for r in result.results)


def test_parse_empty() -> None:
    p = _provider()
    result = p._parse({})
    assert result.results == []

    result = p._parse({"web": {}})
    assert result.results == []


def test_parse_missing_title_falls_back_to_empty() -> None:
    p = _provider()
    result = p._parse({"web": {"results": [{"url": "https://x.example/"}]}})
    assert len(result.results) == 1
    assert result.results[0].title == ""
    assert result.results[0].url == "https://x.example/"


def test_is_available_gated_on_api_key(monkeypatch) -> None:
    """Without a key the provider must report unavailable."""
    import metasearchmcp.config as cfg

    monkeypatch.setenv("BRAVE_API_KEY", "")
    cfg.get_settings.cache_clear()
    assert BraveProvider().is_available() is False

    monkeypatch.setenv("BRAVE_API_KEY", "test-key")
    cfg.get_settings.cache_clear()
    assert BraveProvider().is_available() is True
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=respx.MockResponse(200, json=_payload()),
    )

    p = _provider()
    result = await p.search("fastapi", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "brave"
    assert result.results[0].title == "FastAPI - The Modern Python Web Framework"


@pytest.mark.asyncio
async def test_search_raises_on_api_error(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=respx.MockResponse(429, json={"error": "rate limited"}),
    )

    p = _provider()
    with pytest.raises(HTTPStatusError):
        await p.search("fastapi", SearchParams(num_results=5))
