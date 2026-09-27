"""Unit tests for the official Arch Linux package search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.archlinux import ArchLinuxProvider

_API_URL = "https://archlinux.org/packages/search/json/"

_BAT_NAME_RECORD: dict[str, object] = {
    "pkgname": "bat",
    "pkgbase": "bat",
    "repo": "extra",
    "arch": "x86_64",
    "pkgver": "0.25.0",
    "pkgrel": "1",
    "epoch": 0,
    "pkgdesc": "Cat clone with syntax highlighting and Git integration",
    "url": "https://github.com/sharkdp/bat",
    "filename": "bat-0.25.0-1-x86_64.pkg.tar.zst",
    "compressed_size": 1200000,
    "installed_size": 4500000,
    "build_date": "2025-07-31T17:31:33Z",
    "last_update": "2025-07-31T18:43:44.195Z",
    "flag_date": None,
    "maintainers": ["bob"],
    "licenses": ["Apache-2.0"],
    "groups": [],
    "depends": ["glibc"],
    "provides": [],
}

_Q_RESPONSE: dict[str, object] = {
    "version": 2,
    "limit": 250,
    "valid": True,
    "results": [
        # Description-only match ("combat" contains "bat").
        {
            "pkgname": "combat-tool",
            "repo": "extra",
            "arch": "x86_64",
            "pkgver": "1.0",
            "pkgrel": "2",
            "epoch": 0,
            "pkgdesc": "A tactical combat helper",
            "url": "https://example.com/combat",
            "maintainers": ["alice"],
            "licenses": ["MIT"],
            "build_date": "2024-01-02T00:00:00Z",
            "flag_date": None,
        },
        # Testing-repo duplicate of the canonical package.
        {
            "pkgname": "bat",
            "repo": "extra-testing",
            "arch": "x86_64",
            "pkgver": "0.26.0",
            "pkgrel": "1",
            "epoch": 0,
            "pkgdesc": "Cat clone with syntax highlighting",
            "url": "https://github.com/sharkdp/bat",
            "maintainers": ["bob"],
            "licenses": ["Apache-2.0"],
            "build_date": "2026-01-02T00:00:00Z",
            "flag_date": None,
        },
        # Arch-independent duplicate of the same package.
        {
            "pkgname": "bat",
            "repo": "extra",
            "arch": "any",
            "pkgver": "0.24.0",
            "pkgrel": "3",
            "epoch": 0,
            "pkgdesc": "Cat clone with syntax highlighting",
            "url": "https://github.com/sharkdp/bat",
            "maintainers": [],
            "licenses": ["Apache-2.0"],
            "build_date": "2025-01-01T00:00:00Z",
            "flag_date": "2025-06-01",
        },
        "junk",  # type: ignore[list-item]
    ],
}

_NAME_RESPONSE: dict[str, object] = {
    "version": 2,
    "limit": 250,
    "valid": True,
    "results": [_BAT_NAME_RECORD],
}

_EMPTY_RESPONSE: dict[str, object] = {"valid": True, "results": []}


def _provider() -> ArchLinuxProvider:
    return ArchLinuxProvider()


def _merged() -> list[dict[str, object]]:
    return [
        *_provider()._items(_NAME_RESPONSE),
        *_provider()._items(_Q_RESPONSE),
    ]


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "archlinux"
    assert p.tags == ["web", "code", "developer", "packages"]
    assert "no API key required" in p.description


def test_parse_ranks_exact_name_first_and_dedupes() -> None:
    p = _provider()
    result = p._parse(_merged(), "bat")

    # "bat" (exact) must outrank the description-only "combat-tool" match, and
    # the three "bat" rows must collapse into a single result.
    assert [r.title for r in result.results] == ["bat", "combat-tool"]
    first = result.results[0]
    assert first.rank == 1
    assert first.source == "archlinux.org"
    assert first.provider == "archlinux"
    assert first.url == "https://archlinux.org/packages/extra/x86_64/bat/"
    assert first.published_date == "2025-07-31"
    # The stable x86_64 row wins over extra-testing and arch-independent rows.
    assert first.extra["repo"] == "extra"
    assert first.extra["arch"] == "x86_64"
    assert first.extra["version"] == "0.25.0-1"
    assert first.extra["maintainer"] == "bob"
    assert first.extra["licenses"] == ["Apache-2.0"]
    assert first.extra["depends"] == ["glibc"]
    assert first.extra["homepage"] == "https://github.com/sharkdp/bat"
    assert "v0.25.0-1" in first.snippet
    assert "extra/x86_64" in first.snippet
    assert "Maintainer: bob" in first.snippet
    assert "Updated: 2025-07-31" in first.snippet


def test_parse_orphaned_and_flagged_rows() -> None:
    p = _provider()
    result = p._parse(p._items(_Q_RESPONSE), "bat")
    bat_any = next(r for r in result.results if r.extra["arch"] == "any")

    assert "Orphaned" in bat_any.snippet
    assert "Maintainer:" not in bat_any.snippet
    assert "Flagged out-of-date" in bat_any.snippet
    assert bat_any.extra["maintainer"] == ""
    assert bat_any.extra["flag_date"] == "2025-06-01"


def test_parse_prefix_ranks_above_substring() -> None:
    p = _provider()
    items: list[dict[str, object]] = [
        {"pkgname": "libyaml", "repo": "extra", "arch": "x86_64", "pkgdesc": "yaml"},
        {"pkgname": "yamlcpp", "repo": "extra", "arch": "x86_64", "pkgdesc": "yaml"},
        {"pkgname": "yaml", "repo": "extra", "arch": "x86_64", "pkgdesc": "yaml"},
    ]
    assert [r.title for r in p._parse(items, "yaml").results] == [
        "yaml",
        "yamlcpp",
        "libyaml",
    ]


def test_parse_includes_epoch_in_version() -> None:
    p = _provider()
    items: list[dict[str, object]] = [
        {
            "pkgname": "curl",
            "repo": "core",
            "arch": "x86_64",
            "pkgver": "8.5.0",
            "pkgrel": "2",
            "epoch": 3,
            "pkgdesc": "command line tool and library for transferring data",
        },
    ]
    result = p._parse(items, "curl")
    assert result.results[0].extra["version"] == "3:8.5.0-2"
    assert "v3:8.5.0-2" in result.results[0].snippet


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._items(_EMPTY_RESPONSE) == []
    assert p._items({}) == []
    assert p._items(None) == []
    assert p._items("junk") == []
    assert p._items({"results": "junk"}) == []
    assert p._parse([], "bat").results == []
    assert p._parse([{"pkgname": ""}, {"pkgname": "  "}], "bat").results == []
    # Non-dict entries are filtered by _items before _parse sees them.
    assert all(isinstance(item, dict) for item in p._items(_Q_RESPONSE))


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse(_merged(), "bat", limit=1).results) == 1


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_queries_name_and_fulltext(respx_mock) -> None:
    import respx

    respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_Q_RESPONSE)
    )

    p = _provider()
    result = await p.search("bat", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["bat", "combat-tool"]
    assert len(respx_mock.calls) == 2
    param_sets = [dict(call.request.url.params) for call in respx_mock.calls]
    assert any(params.get("name") == "bat" for params in param_sets)
    assert any(
        params.get("q") == "bat" and params.get("limit") == "250"
        for params in param_sets
    )


@pytest.mark.asyncio
async def test_search_multi_word_query_skips_name_lookup(respx_mock) -> None:
    import respx

    respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_Q_RESPONSE)
    )

    p = _provider()
    result = await p.search("yaml parser", SearchParams(num_results=5))

    assert len(respx_mock.calls) == 1
    params = dict(respx_mock.calls[0].request.url.params)
    assert params.get("q") == "yaml parser"
    assert "name" not in params
    assert result.results


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE)
    )

    p = _provider()
    result = await p.search("no-such-arch-package-xyz", SearchParams(num_results=5))
    assert result.results == []
