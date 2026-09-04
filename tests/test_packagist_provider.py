"""Unit tests for the Packagist PHP package search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.packagist import PackagistProvider

_SAMPLE_RESPONSE: dict[str, object] = {
    "total": 5957,
    "results": [
        {
            "name": "laravel/framework",
            "description": "The Laravel Framework.",
            "url": "https://packagist.org/packages/laravel/framework",
            "repository": "https://github.com/laravel/framework",
            "downloads": 572491399,
            "favers": 35381,
            "abandoned": None,
        },
        {
            "name": "abandoned/pkg",
            "description": "An abandoned package.",
            "url": "https://packagist.org/packages/abandoned/pkg",
            "repository": "",
            "downloads": 100,
            "favers": 0,
            "abandoned": True,
        },
        {
            "name": "replaced/pkg",
            "description": "Replaced by a fork.",
            "url": "https://packagist.org/packages/replaced/pkg",
            "downloads": 5,
            "favers": 1,
            "abandoned": "fork/replacement",
        },
        {
            # Missing name -> skipped.
            "description": "ghost",
            "downloads": 1,
            "favers": 0,
            "abandoned": None,
        },
        "junk",
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"total": 0, "results": []}


def _provider() -> PackagistProvider:
    return PackagistProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "packagist"
    assert p.tags == ["web", "code", "developer", "packages"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 3
    r = result.results[0]
    assert r.title == "laravel/framework"
    assert r.url == "https://packagist.org/packages/laravel/framework"
    assert "The Laravel Framework" in r.snippet
    assert "Downloads: 572,491,399" in r.snippet
    assert "Favers: 35,381" in r.snippet
    assert r.source == "packagist.org"
    assert r.provider == "packagist"
    assert r.rank == 1
    assert r.extra["package_name"] == "laravel/framework"
    assert r.extra["repository"] == "https://github.com/laravel/framework"
    assert r.extra["downloads"] == 572491399
    assert r.extra["favers"] == 35381
    assert r.extra["abandoned_reason"] == ""
    assert r.extra["total_hits"] == 5957


def test_parse_abandoned_flags() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    # Abandoned=True -> generic note.
    assert result.results[1].extra["abandoned_reason"] == "abandoned"
    # Abandoned=<replacement name> -> note with the replacement package.
    assert (
        result.results[2].extra["abandoned_reason"]
        == "abandoned (replacement: fork/replacement)"
    )


def test_parse_skips_nameless_and_non_dict_items() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    # The nameless item and the "junk" string are both skipped.
    assert all(r.title for r in result.results)


def test_parse_url_fallback_and_blank_description() -> None:
    p = _provider()
    result = p._parse(
        {
            "total": 1,
            "results": [{"name": "vendor/lib", "description": "  ", "downloads": 0}],
        }
    )
    r = result.results[0]
    # Canonical page URL is derived from the package name.
    assert r.url == "https://packagist.org/packages/vendor/lib"
    assert r.snippet == ""
    assert r.extra["favers"] == 0
    assert r.extra["abandoned_reason"] == ""


def test_parse_limit_and_empty() -> None:
    p = _provider()
    assert len(p._parse(_SAMPLE_RESPONSE, limit=1).results) == 1
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []
    assert p._parse({"results": ["junk", None, 42]}).results == []
    assert p._parse("junk").results == []  # type: ignore[arg-type]


def test_parse_snippet_capped_at_shared_limit() -> None:
    from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH

    long_description = "x" * (MAX_SNIPPET_LENGTH + 200)
    result = _provider()._parse(
        {
            "results": [
                {
                    "name": "vendor/long",
                    "description": long_description,
                    "downloads": 0,
                    "favers": 0,
                    "abandoned": None,
                }
            ]
        }
    )
    assert len(result.results[0].snippet) == MAX_SNIPPET_LENGTH


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_query_and_per_page(respx_mock) -> None:
    import respx

    respx_mock.get("https://packagist.org/search.json").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("laravel", SearchParams(num_results=5))

    assert len(result.results) == 3
    request = respx_mock.calls.last.request
    assert request.url.params["q"] == "laravel"
    assert request.url.params["per_page"] == "5"


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://packagist.org/search.json").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("no-such-package-xyz", SearchParams(num_results=5))
    assert result.results == []
