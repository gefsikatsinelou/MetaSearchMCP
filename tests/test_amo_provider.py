"""Unit tests for the Mozilla Add-ons (AMO) browser extension search provider."""

from __future__ import annotations

import httpx
import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.amo import AmoProvider

_SEARCH_RESPONSE: dict[str, object] = {
    "count": 1990,
    "results": [
        {
            "id": 607454,
            "slug": "ublock-origin",
            "guid": "uBlock0@raymondhill.net",
            "name": {"en-US": "uBlock Origin", "de": "uBlock Origin"},
            "summary": {
                "en-US": (
                    "Finally, an efficient wide-spectrum content blocker. "
                    "Easy on CPU and memory."
                )
            },
            "description": {"en-US": "A long-form description."},
            "current_version": {"version": "1.74.0"},
            "average_daily_users": 10990791,
            "weekly_downloads": 88213,
            "ratings": {"average": 4.8007, "count": 22082},
            "authors": [{"name": "Raymond Hill"}, {"name": "gorhill"}],
            "categories": ["privacy-security"],
            "tags": ["privacy", "security", "ad blocker"],
            "type": "extension",
            "status": "public",
            "is_experimental": False,
            "last_updated": "2026-09-06T14:01:41Z",
        },
        {
            "id": 123,
            "slug": "no-name-test",
            "name": {"en-US": "", "fr": "Extension sans nom."},
            "summary": {"fr": "Extension sans nom."},
            "type": "extension",
            "status": "public",
            "is_experimental": False,
            "last_updated": None,
        },
        {
            "id": 456,
            "slug": "theme-x",
            "name": {"en-US": "Theme X"},
            "type": "theme",
            "status": "public",
            "is_experimental": False,
        },
        {
            "id": 789,
            "slug": "experimental-thing",
            "name": {"en-US": "Experimental Thing"},
            "type": "extension",
            "status": "public",
            "is_experimental": True,
        },
        "junk",  # type: ignore[list-item]
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"results": [], "count": 0}


def _provider() -> AmoProvider:
    return AmoProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "amo"
    assert p.tags == ["web", "code", "developer", "plugins"]
    assert "no API key required" in p.description


def test_parse_basic_hit_fields() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)

    assert len(result.results) == 2
    first = result.results[0]
    assert first.title == "uBlock Origin"
    assert first.url == "https://addons.mozilla.org/firefox/addon/ublock-origin/"
    assert first.source == "addons.mozilla.org"
    assert first.provider == "amo"
    assert first.rank == 1
    assert "content blocker" in first.snippet
    assert "v1.74.0" in first.snippet
    assert "Users: 10,990,791" in first.snippet
    assert "Weekly downloads: 88,213" in first.snippet
    assert "Rating: 4.8/5 (22082)" in first.snippet
    assert "Author: Raymond Hill, gorhill" in first.snippet
    assert first.published_date == "2026-09-06"
    assert first.extra["slug"] == "ublock-origin"
    assert first.extra["version"] == "1.74.0"
    assert first.extra["average_daily_users"] == 10990791
    assert first.extra["rating"] == 4.8
    assert first.extra["rating_count"] == 22082
    assert first.extra["categories"] == ["privacy-security"]
    assert first.extra["tags"] == ["privacy", "security", "ad blocker"]


def test_parse_filters_themes_and_experimental() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    # Theme and experimental extension hits are dropped.
    assert all(r.extra["slug"] != "theme-x" for r in result.results)
    assert all(r.extra["slug"] != "experimental-thing" for r in result.results)


def test_parse_localized_fallback_and_missing_fields() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    second = result.results[1]
    # Empty en-US name falls back to any other locale.
    assert second.title == "Extension sans nom."
    assert second.url == "https://addons.mozilla.org/firefox/addon/no-name-test/"
    assert second.published_date is None
    assert second.extra["version"] == ""
    assert second.extra["average_daily_users"] == 0
    assert second.extra["rating"] is None


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []
    assert p._parse(None).results == []
    assert p._parse("junk").results == []
    assert p._parse({"results": "junk"}).results == []
    assert p._parse({"results": [{}]}).results == []
    assert p._parse({"results": [{"name": {"en-US": ""}}]}).results == []


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse(_SEARCH_RESPONSE, limit=1).results) == 1


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_gets_api(respx_mock) -> None:
    import respx

    respx_mock.get("https://addons.mozilla.org/api/v5/addons/search/").mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE)
    )

    p = _provider()
    result = await p.search("ublock", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].title == "uBlock Origin"
    call = respx_mock.calls[0]
    assert "q=ublock" in str(call.request.url)
    assert "page_size=5" in str(call.request.url)
    assert "type=extension" in str(call.request.url)


@pytest.mark.asyncio
async def test_search_http_error_raises(respx_mock) -> None:
    import respx

    respx_mock.get("https://addons.mozilla.org/api/v5/addons/search/").mock(
        return_value=respx.MockResponse(500)
    )

    p = _provider()
    with pytest.raises(httpx.HTTPStatusError):
        await p.search("ublock", SearchParams(num_results=5))
