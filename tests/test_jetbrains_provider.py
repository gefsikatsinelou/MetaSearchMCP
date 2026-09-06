"""Unit tests for the JetBrains Marketplace plugin search provider."""

from __future__ import annotations

import httpx
import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.jetbrains import JetbrainsProvider

_SEARCH_RESPONSE: dict[str, object] = {
    "plugins": [
        {
            "id": 7793,
            "xmlId": "org.intellij.plugins.markdown",
            "link": "/plugin/7793-markdown",
            "name": "Markdown",
            "preview": (
                "Provides editing assistance for Markdown files within the IDE. "
                "Full support for vanilla Markdown syntax."
            ),
            "downloads": 14343745,
            "pricingModel": "FREE",
            "icon": "/files/7793/1160004/icon/default.svg",
            "cdate": 1788353331000,
            "rating": 2.59,
            "hasSource": True,
            "tags": ["Programming Language"],
            "vendor": {"name": "JetBrains s.r.o.", "isVerified": True},
        },
        {
            "id": 23231,
            "xmlId": "com.example.obscure-markdown",
            "link": "/plugin/23231-obscure-markdown",
            "name": "Obscure Markdown Fork",
            "preview": "A small unofficial fork.",
            "downloads": 28435,
            "pricingModel": "FREE",
            "cdate": None,
            "rating": None,
            "vendor": {"name": "anon", "isVerified": False},
        },
        "junk",  # type: ignore[list-item]
    ]
}

_EMPTY_RESPONSE: dict[str, object] = {"plugins": []}


def _provider() -> JetbrainsProvider:
    return JetbrainsProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "jetbrains"
    assert p.tags == ["web", "code", "developer", "plugins"]
    assert "no API key required" in p.description


def test_parse_basic_hit_fields() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)

    assert len(result.results) == 2
    first = result.results[0]
    assert first.title == "Markdown"
    assert first.url == "https://plugins.jetbrains.com/plugin/7793-markdown"
    assert first.source == "plugins.jetbrains.com"
    assert first.provider == "jetbrains"
    assert first.rank == 1
    assert "editing assistance for Markdown" in first.snippet
    assert "Downloads: 14,343,745" in first.snippet
    assert "Rating: 2.59/5" in first.snippet
    assert "Pricing: FREE" in first.snippet
    assert "Vendor: JetBrains s.r.o. (verified)" in first.snippet
    assert first.published_date == "2026-09-02"
    assert first.extra["downloads"] == 14343745
    assert first.extra["rating"] == 2.59
    assert first.extra["pricing_model"] == "FREE"
    assert first.extra["vendor"] == "JetBrains s.r.o."
    assert first.extra["vendor_verified"] is True
    assert first.extra["tags"] == ["Programming Language"]


def test_parse_reranks_by_downloads() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    # Higher-download plugin surfaces first regardless of API order.
    assert result.results[0].title == "Markdown"
    assert result.results[1].title == "Obscure Markdown Fork"


def test_parse_unverified_vendor_and_missing_fields() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    second = result.results[1]
    assert "Vendor: anon" in second.snippet
    assert "(verified)" not in second.snippet
    assert second.published_date is None
    assert second.extra["rating"] is None
    assert second.extra["downloads"] == 28435


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []
    assert p._parse(None).results == []
    assert p._parse("junk").results == []
    assert p._parse({"plugins": "junk"}).results == []
    assert p._parse({"plugins": [{}]}).results == []


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse(_SEARCH_RESPONSE, limit=1).results) == 1


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_gets_api(respx_mock) -> None:
    import respx

    respx_mock.get("https://plugins.jetbrains.com/api/searchPlugins").mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE)
    )

    p = _provider()
    result = await p.search("markdown", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].title == "Markdown"
    call = respx_mock.calls[0]
    assert "search=markdown" in str(call.request.url)
    assert "max=5" in str(call.request.url)


@pytest.mark.asyncio
async def test_search_http_error_raises(respx_mock) -> None:
    import respx

    respx_mock.get("https://plugins.jetbrains.com/api/searchPlugins").mock(
        return_value=respx.MockResponse(500)
    )

    p = _provider()
    with pytest.raises(httpx.HTTPStatusError):
        await p.search("markdown", SearchParams(num_results=5))
