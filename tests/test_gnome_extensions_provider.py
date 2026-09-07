"""Unit tests for the GNOME Shell extension search provider."""

from __future__ import annotations

import httpx
import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.gnome_extensions import GnomeExtensionsProvider

_SEARCH_RESPONSE: dict[str, object] = {
    "metadata": None,
    "extensions": [
        {
            "uuid": "dash-to-dock@micxgx.gmail.com",
            "name": "Dash to Dock",
            "creator": "micxgx",
            "creator_url": "/accounts/profile/micxgx",
            "pk": 307,
            "description": (
                "A dock for the GNOME Shell. This extension moves the dash "
                "out of the overview transforming it into a dock."
            ),
            "link": "/extension/307/dash-to-dock/",
            "icon": "/static/images/plugin.png",
            "screenshot": "/extension-data/screenshots/screenshot_307.png",
            "downloads": 11702002,
            "url": "https://github.com/micheleg/dash-to-dock",
            "shell_version_map": {
                "3.36": {"pk": 2323, "version": 69},
                "40": {"pk": 2323, "version": 69},
                "45.beta": {"pk": 2323, "version": 70},
                "47": {"pk": 2323, "version": 71},
            },
        },
        {
            # Low-download fork: should be re-ranked after the canonical one.
            "uuid": "dash-to-dock-fork@example.com",
            "name": "Dash to Dock Fork",
            "creator": "forker",
            "pk": 4704,
            "description": "A fork with extra options.",
            "link": "/extension/4704/dash-to-dock-fork/",
            "downloads": 250,
            "shell_version_map": {"47": {"pk": 9999, "version": 1}},
        },
        {"name": "", "uuid": "no-name@example.com", "pk": 1},
        {"uuid": "no-link@example.com", "name": "No Link", "pk": 0},
        "junk",  # type: ignore[list-item]
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"extensions": []}


def _provider() -> GnomeExtensionsProvider:
    return GnomeExtensionsProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "gnome_extensions"
    assert p.tags == ["web", "code", "developer", "plugins"]
    assert "no API key required" in p.description


def test_parse_basic_hit_fields() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)

    assert len(result.results) == 2
    first = result.results[0]
    assert first.title == "Dash to Dock"
    assert first.url == "https://extensions.gnome.org/extension/307/dash-to-dock/"
    assert first.source == "extensions.gnome.org"
    assert first.provider == "gnome_extensions"
    assert first.rank == 1
    assert "moves the dash" in first.snippet
    assert "Downloads: 11,702,002" in first.snippet
    assert "GNOME Shell 3.36-47" in first.snippet
    assert "Author: micxgx" in first.snippet
    assert first.published_date is None
    assert first.extra["uuid"] == "dash-to-dock@micxgx.gmail.com"
    assert first.extra["extension_id"] == 307
    assert first.extra["author"] == "micxgx"
    assert first.extra["downloads"] == 11702002
    # Numeric ordering across widths: 40 sits between 3.x and 47, and the
    # unstable "45.beta" key is not mistaken for a newer major version.
    assert first.extra["shell_versions"] == "3.36-47"
    assert first.extra["homepage"].startswith("https://github.com/")
    # Site-relative screenshot path is absolutized.
    assert (
        first.extra["screenshot_url"]
        == "https://extensions.gnome.org/extension-data/screenshots/screenshot_307.png"
    )


def test_parse_reranks_by_downloads() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    # Canonical (high-download) extension surfaces before the niche fork.
    assert result.results[0].extra["uuid"] == "dash-to-dock@micxgx.gmail.com"
    assert result.results[1].extra["uuid"] == "dash-to-dock-fork@example.com"


def test_parse_handles_missing_fields() -> None:
    p = _provider()
    second = p._parse(_SEARCH_RESPONSE).results[1]
    assert second.title == "Dash to Dock Fork"
    assert second.extra["shell_versions"] == "47"
    assert second.extra["homepage"] == ""
    assert second.extra["screenshot_url"] == ""
    assert "Downloads: 250" in second.snippet


def test_parse_skips_unusable_records() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    # Nameless record and a record with neither link nor numeric id are dropped.
    dropped = {"no-name@example.com", "no-link@example.com"}
    assert all(r.extra["uuid"] not in dropped for r in result.results)


def test_shell_range_helpers() -> None:
    from metasearchmcp.providers.gnome_extensions import _shell_range

    assert _shell_range({"3.36": 1, "40": 2}) == "3.36-40"
    assert _shell_range({"40": 1}) == "40"
    assert _shell_range({"45.beta": 1, "46": 2}) == "45.beta-46"
    assert _shell_range({}) == ""
    assert _shell_range(None) == ""
    assert _shell_range("junk") == ""


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []
    assert p._parse(None).results == []
    assert p._parse("junk").results == []
    assert p._parse({"extensions": "junk"}).results == []
    assert p._parse({"extensions": [{}]}).results == []
    assert p._parse({"extensions": [{"name": ""}]}).results == []


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse(_SEARCH_RESPONSE, limit=1).results) == 1


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_gets_api(respx_mock) -> None:
    import respx

    respx_mock.get("https://extensions.gnome.org/extension-query/").mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE)
    )

    p = _provider()
    result = await p.search("dash to dock", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].title == "Dash to Dock"
    call = respx_mock.calls[0]
    assert "search=dash+to+dock" in str(call.request.url)
    assert "page=1" in str(call.request.url)


@pytest.mark.asyncio
async def test_search_http_error_raises(respx_mock) -> None:
    import respx

    respx_mock.get("https://extensions.gnome.org/extension-query/").mock(
        return_value=respx.MockResponse(500)
    )

    p = _provider()
    with pytest.raises(httpx.HTTPStatusError):
        await p.search("dash to dock", SearchParams(num_results=5))
