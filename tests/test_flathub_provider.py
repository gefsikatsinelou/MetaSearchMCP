"""Unit tests for the Flathub (Linux desktop app) search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.flathub import FlathubProvider

_SEARCH_RESPONSE: dict[str, object] = {
    "hits": [
        {
            "name": "Obsidian",
            "summary": "Markdown-based knowledge base",
            "description": "A powerful knowledge base on local Markdown files.",
            "id": "md_obsidian_Obsidian",
            "app_id": "md.obsidian.Obsidian",
            "project_license": "LicenseRef-proprietary",
            "developer_name": "Obsidian",
            "icon": "https://dl.flathub.org/media/icon.png",
            "installs_last_month": 80530,
            "favorites_count": 571,
        },
        {
            "name": "GIMP",
            "summary": "Create images and edit photographs",
            "app_id": "org.gimp.GIMP",
            "project_license": "GPL-3.0",
            "developer_name": "The GIMP Team",
            "installs_last_month": 120000,
            "favorites_count": 1000,
        },
        "junk",  # type: ignore[list-item]
    ]
}

_EMPTY_RESPONSE: dict[str, object] = {"hits": []}


def _provider() -> FlathubProvider:
    return FlathubProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "flathub"
    assert p.tags == ["web", "code", "developer", "apps"]
    assert "no API key required" in p.description


def test_parse_basic_hit_fields() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)

    assert len(result.results) == 2
    first = result.results[0]
    assert first.title == "Obsidian (md.obsidian.Obsidian)"
    assert first.url == "https://flathub.org/apps/md.obsidian.Obsidian"
    assert first.source == "flathub.org"
    assert first.provider == "flathub"
    assert first.rank == 1
    assert "Markdown-based knowledge base" in first.snippet
    assert "Developer: Obsidian" in first.snippet
    assert "Installs/mo: 80,530" in first.snippet
    assert first.extra["app_id"] == "md.obsidian.Obsidian"
    assert first.extra["developer"] == "Obsidian"
    assert first.extra["installs_last_month"] == 80530
    assert first.extra["favorites_count"] == 571
    assert first.extra["icon"].startswith("https://")


def test_parse_falls_back_to_app_id_title() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    # Hit without a separate name uses the app id as display title.
    assert result.results[1].title == "GIMP (org.gimp.GIMP)"


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []
    assert p._parse(None).results == []
    assert p._parse("junk").results == []
    assert p._parse({"hits": "junk"}).results == []
    assert p._parse({"hits": [{}]}).results == []


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse(_SEARCH_RESPONSE, limit=1).results) == 1


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_posts_to_api(respx_mock) -> None:
    import respx

    respx_mock.post("https://flathub.org/api/v2/search").mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE)
    )

    p = _provider()
    result = await p.search("obsidian", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].title == "Obsidian (md.obsidian.Obsidian)"
    call = respx_mock.calls[0]
    assert call.request.url.path == "/api/v2/search"
    assert "obsidian" in call.request.content.decode()


@pytest.mark.asyncio
async def test_search_404_fails_gracefully(respx_mock) -> None:
    import respx

    respx_mock.post("https://flathub.org/api/v2/search").mock(
        return_value=respx.MockResponse(404)
    )

    p = _provider()
    result = await p.search("obsidian", SearchParams(num_results=5))
    assert result.results == []
