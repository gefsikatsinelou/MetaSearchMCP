"""Unit tests for the Snapcraft (Snap Store) Linux app search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.snapcraft import SnapcraftProvider

_SEARCH_RESPONSE: dict[str, object] = {
    "results": [
        {
            "name": "obsidian",
            "snap-id": "XSpRD8poWONFIT1z9TleS4XrS1u0MlfG",
            "revision": {
                "version": "1.13.7",
                "base": "core24",
                "confinement": "classic",
            },
            "snap": {
                "title": "Obsidian",
                "summary": "A knowledge base on local Markdown files",
                "description": "Powerful note-taking on local Markdown files.",
                "license": "Proprietary",
                "categories": [{"name": "productivity"}, {"name": "office"}],
                "media": [
                    {
                        "type": "icon",
                        "url": "https://dashboard.snapcraft.io/site_media/appmedia/obsidian.png",
                        "width": 512,
                        "height": 512,
                    }
                ],
                "publisher": {
                    "display-name": "Obsidian",
                    "username": "obsidianmd",
                    "validation": "unproven",
                },
                "store-url": "https://snapcraft.io/obsidian",
            },
        },
        {
            "name": "joplin-desktop",
            "snap-id": "bJW03EkiFdbjIuk3MBBoc51n1DcHw70B",
            "revision": {"version": "3.2.1", "confinement": "strict"},
            "snap": {
                "title": "Joplin",
                "summary": "Note-taking and to-do application",
                "description": "A note-taking and to-do application.",
                "license": "MIT",
                "categories": [],
                "media": [],
                "publisher": {"display-name": "Laurent Cozic", "username": "joplin"},
                "store-url": "https://snapcraft.io/joplin-desktop",
            },
        },
        "junk",  # type: ignore[list-item]
        {"name": "orphan"},
    ]
}

_EMPTY_RESPONSE: dict[str, object] = {"results": []}


def _provider() -> SnapcraftProvider:
    return SnapcraftProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "snapcraft"
    assert p.tags == ["web", "code", "developer", "apps"]
    assert "no API key required" in p.description


def test_parse_basic_hit_fields() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)

    assert len(result.results) == 2
    first = result.results[0]
    assert first.title == "Obsidian (obsidian)"
    assert first.url == "https://snapcraft.io/obsidian"
    assert first.source == "snapcraft.io"
    assert first.provider == "snapcraft"
    assert first.rank == 1
    assert "A knowledge base on local Markdown files" in first.snippet
    assert "Publisher: Obsidian" in first.snippet
    assert "Version: 1.13.7" in first.snippet
    assert "License: Proprietary" in first.snippet
    assert "Categories: productivity, office" in first.snippet
    assert first.extra["snap_id"] == "XSpRD8poWONFIT1z9TleS4XrS1u0MlfG"
    assert first.extra["publisher"] == "Obsidian"
    assert first.extra["version"] == "1.13.7"
    assert first.extra["confinement"] == "classic"
    assert first.extra["categories"] == ["productivity", "office"]
    assert first.extra["icon"].startswith("https://")


def test_parse_skips_entries_without_snap_metadata() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    # Both the plain "junk" string and the name-only dict are skipped.
    assert len(result.results) == 2


def test_parse_missing_store_url_falls_back_to_canonical() -> None:
    p = _provider()
    payload = {
        "results": [
            {
                "name": "hello",
                "snap": {"title": "Hello World", "summary": "Demo snap"},
            }
        ]
    }
    result = p._parse(payload)
    assert len(result.results) == 1
    assert result.results[0].url == "https://snapcraft.io/hello"


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []
    assert p._parse(None).results == []
    assert p._parse("junk").results == []
    assert p._parse({"results": "junk"}).results == []
    assert p._parse({"results": [{}]}).results == []
    assert p._parse({"results": [{"name": "x"}]}).results == []


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse(_SEARCH_RESPONSE, limit=1).results) == 1


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_gets_find_api(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.snapcraft.io/v2/snaps/find").mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE)
    )

    p = _provider()
    result = await p.search("obsidian", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].title == "Obsidian (obsidian)"
    call = respx_mock.calls[0]
    assert call.request.url.path == "/v2/snaps/find"
    assert call.request.url.params["q"] == "obsidian"
    assert call.request.headers["Snap-Device-Series"] == "16"


@pytest.mark.asyncio
async def test_search_404_fails_gracefully(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.snapcraft.io/v2/snaps/find").mock(
        return_value=respx.MockResponse(404)
    )

    p = _provider()
    result = await p.search("obsidian", SearchParams(num_results=5))
    assert result.results == []
