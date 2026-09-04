"""Unit tests for the Hex.pm package search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.hex import HexProvider

_SAMPLE_RESPONSE: list[dict[str, object]] = [
    {
        "name": "ecto",
        "latest_stable_version": "3.14.2",
        "latest_version": "3.14.2",
        "html_url": "https://hex.pm/packages/ecto",
        "downloads": {"all": 146283055, "recent": 4369089},
        "updated_at": "2026-08-25T09:12:08.458607Z",
        "meta": {
            "description": (
                "A toolkit for data mapping and language integrated query for Elixir"
            ),
            "licenses": ["Apache-2.0"],
        },
    },
    {
        "name": "phoenix",
        "latest_stable_version": "",
        "latest_version": "1.8.0-rc.0",
        "html_url": "https://hex.pm/packages/phoenix",
        "downloads": {"all": 1000},
        "meta": {
            "description": "Peace of mind from prototype to production",
            "licenses": ["MIT", "Apache-2.0"],
        },
    },
    {
        "name": "legacy_pkg",
        "latest_stable_version": "0.9.0",
        "html_url": "",
        "downloads": 5,
        "meta": {"description": "", "licenses": []},
    },
    {
        # Missing name -> skipped.
        "latest_stable_version": "1.0.0",
        "meta": {"description": "ghost"},
    },
    "junk",
    None,
]

_EMPTY_RESPONSE: list[dict[str, object]] = []


def _provider() -> HexProvider:
    return HexProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "hex"
    assert p.tags == ["web", "code", "developer", "packages"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 3
    r = result.results[0]
    assert r.title == "ecto"
    assert r.url == "https://hex.pm/packages/ecto"
    assert "A toolkit for data mapping" in r.snippet
    assert "v3.14.2" in r.snippet
    assert "Downloads: 146,283,055" in r.snippet
    assert r.source == "hex.pm"
    assert r.provider == "hex"
    assert r.rank == 1
    assert r.extra["package_name"] == "ecto"
    assert r.extra["version"] == "3.14.2"
    assert r.extra["license"] == "Apache-2.0"
    assert r.extra["total_downloads"] == 146283055


def test_parse_version_falls_back_to_latest() -> None:
    # No stable version -> pre-release latest_version is reported.
    r = _provider()._parse(_SAMPLE_RESPONSE).results[1]
    assert r.extra["version"] == "1.8.0-rc.0"
    assert r.extra["license"] == "MIT, Apache-2.0"


def test_parse_url_fallback_and_blank_description() -> None:
    r = _provider()._parse(_SAMPLE_RESPONSE).results[2]
    # Canonical page URL is derived from the package name.
    assert r.url == "https://hex.pm/packages/legacy_pkg"
    # Blank description -> snippet carries only the version part.
    assert r.snippet == "v0.9.0"
    # Non-dict downloads payload degrades to zero.
    assert r.extra["total_downloads"] == 0
    assert r.extra["version"] == "0.9.0"


def test_parse_skips_nameless_and_non_dict_items() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert all(r.title for r in result.results)
    assert len(result.results) == 3


def test_parse_limit_and_empty() -> None:
    p = _provider()
    assert len(p._parse(_SAMPLE_RESPONSE, limit=1).results) == 1
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse("junk").results == []  # type: ignore[arg-type]
    assert p._parse(None).results == []  # type: ignore[arg-type]


def test_parse_snippet_capped_at_shared_limit() -> None:
    from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH

    long_description = "x" * (MAX_SNIPPET_LENGTH + 200)
    result = _provider()._parse(
        [
            {
                "name": "vendor/long",
                "html_url": "https://hex.pm/packages/vendor/long",
                "meta": {"description": long_description},
            }
        ]
    )
    assert len(result.results[0].snippet) == MAX_SNIPPET_LENGTH


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_query_and_sort(respx_mock) -> None:
    import respx

    respx_mock.get("https://hex.pm/api/packages").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("ecto", SearchParams(num_results=5))

    assert len(result.results) == 3
    request = respx_mock.calls.last.request
    assert request.url.params["search"] == "ecto"
    assert request.url.params["sort"] == "downloads"


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://hex.pm/api/packages").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("no-such-package-xyz", SearchParams(num_results=5))
    assert result.results == []
