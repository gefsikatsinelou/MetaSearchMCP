"""Unit tests for the AUR (Arch Linux User Repository) package search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.aur import AurProvider

_SEARCH_RESPONSE: dict[str, object] = {
    "resultcount": 4,
    "type": "search",
    "version": 5,
    "results": [
        {
            "Name": "goneovim-bin",
            "Version": "0.6.17-1",
            "Description": "Neovim GUI written in Golang",
            "NumVotes": 8,
            "Popularity": 0.000023,
            "Maintainer": "Dominiquini",
            "URL": "https://github.com/akiyosi/goneovim",
            "OutOfDate": None,
        },
        {
            "Name": "bat",
            "Version": "0.25.0-1",
            "Description": "Cat clone with syntax highlighting and Git integration",
            "NumVotes": 4512,
            "Popularity": 3.456,
            "Maintainer": "Morganamilo",
            "URL": "https://github.com/sharkdp/bat",
            "OutOfDate": None,
        },
        {
            "Name": "altayibat-bin",
            "Version": "1.0.0-1",
            "Description": "نظام الطيبات",
            "NumVotes": 0,
            "Popularity": 0,
            "Maintainer": "ahmed_x86",
            "URL": None,
            "OutOfDate": None,
        },
        {
            "Name": "bat-extras",
            "Version": "2023.08.08-1",
            "Description": "Bash scripts to integrate bat",
            "NumVotes": 64,
            "Popularity": 0.3,
            "Maintainer": None,
            "URL": "https://github.com/eth-p/bat-extras",
            "OutOfDate": 1774827726,
        },
        "junk",  # type: ignore[list-item]
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"resultcount": 0, "type": "search", "results": []}


def _provider() -> AurProvider:
    return AurProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "aur"
    assert p.tags == ["web", "code", "developer", "packages"]
    assert "no API key required" in p.description


def test_parse_ranks_by_votes_and_keeps_rich_fields() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)

    # Highest-vote package ("bat") must surface first, not alphabetical "altayibat-bin".
    expected = ["bat", "bat-extras", "goneovim-bin", "altayibat-bin"]
    assert [r.title for r in result.results] == expected
    first = result.results[0]
    assert first.url == "https://github.com/sharkdp/bat"
    assert first.source == "aur.archlinux.org"
    assert first.provider == "aur"
    assert first.rank == 1
    assert "v0.25.0-1" in first.snippet
    assert "Votes: 4,512" in first.snippet
    assert "Maintainer: Morganamilo" in first.snippet
    assert first.extra["package_name"] == "bat"
    assert first.extra["version"] == "0.25.0-1"
    assert first.extra["votes"] == 4512
    assert abs(first.extra["popularity"] - 3.456) < 1e-9
    assert first.extra["maintainer"] == "Morganamilo"
    assert first.extra["out_of_date"] is None


def test_parse_orphaned_and_out_of_date() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    bat_extras = next(r for r in result.results if r.title == "bat-extras")
    assert "Orphaned" in bat_extras.snippet
    assert "Maintainer:" not in bat_extras.snippet
    assert bat_extras.extra["maintainer"] == ""
    assert bat_extras.extra["out_of_date"] == "1774827726"


def test_parse_falls_back_to_canonical_url() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    altayibat = next(r for r in result.results if r.title == "altayibat-bin")
    assert altayibat.url == "https://aur.archlinux.org/packages/altayibat-bin"


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []
    assert p._parse(None).results == []
    assert p._parse("junk").results == []
    assert p._parse({"results": "junk"}).results == []
    assert p._parse({"results": [{"Name": ""}, 42]}).results == []


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse(_SEARCH_RESPONSE, limit=2).results) == 2


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_rpc_endpoint(respx_mock) -> None:
    import respx

    respx_mock.get("https://aur.archlinux.org/rpc/").mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE)
    )

    p = _provider()
    result = await p.search("bat", SearchParams(num_results=5))

    expected = ["bat", "bat-extras", "goneovim-bin", "altayibat-bin"]
    assert [r.title for r in result.results] == expected
    call = respx_mock.calls[0]
    assert call.request.url.params["v"] == "5"
    assert call.request.url.params["type"] == "search"
    assert call.request.url.params["arg"] == "bat"


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://aur.archlinux.org/rpc/").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE)
    )

    p = _provider()
    result = await p.search("no-such-aur-package-xyz", SearchParams(num_results=5))
    assert result.results == []
