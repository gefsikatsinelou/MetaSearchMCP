"""Unit tests for the r-universe (CRAN / R packages) search provider."""

from __future__ import annotations

import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.runiverse import RUniverseProvider

_SEARCH_URL = "https://r-universe.dev/api/search"

_SEARCH_RESPONSE: dict[str, object] = {
    "query": "ggplot2",
    "skip": 0,
    "limit": 10,
    "total": 3,
    "results": [
        {
            "Package": "ggplot2",
            "Title": "Create Elegant Data Visualisations Using the Grammar of Graphics",
            "Description": (
                "A system for 'declaratively' creating graphics,\n"
                '  based on "The Grammar of Graphics".'
            ),
            "_user": "tidyverse",
            "_usedby": 8859,
            "stars": 6991,
            "topics": ["data-visualisation", "visualisation", "data-visualisation"],
            "updated": 1788364007,
            "maintainer": {
                "name": "Thomas Lin Pedersen",
                "login": "thomasp85",
                "email": "thomas.pedersen@posit.co",
            },
        },
        {
            "Package": "MASS",
            "Title": "Support Functions and Datasets for Venables and Ripley's MASS",
            "Description": "Functions and datasets to support Venables and Ripley.",
            "_user": "cran",
            "_usedby": 7638,
            "updated": 1735689600,
            "maintainer": {"name": "Brian Ripley", "login": "ripley"},
        },
        {
            "Package": "alienpkg",
            "Title": "A package with no universe metadata",
            "Description": "",
            "maintainer": None,
            "stars": "many",
            "_usedby": -1,
            "topics": "not-a-list",
            "updated": None,
        },
        "junk",  # type: ignore[list-item]
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"results": [], "total": 0}


def _provider() -> RUniverseProvider:
    return RUniverseProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "runiverse"
    assert p.tags == ["web", "code", "developer", "packages"]
    assert "no API key required" in p.description


def test_parse_keeps_index_order_and_rich_fields() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)

    assert [r.title for r in result.results] == ["ggplot2", "MASS", "alienpkg"]
    first = result.results[0]
    assert first.url == "https://tidyverse.r-universe.dev/ggplot2"
    assert first.source == "r-universe.dev"
    assert first.provider == "runiverse"
    assert first.rank == 1
    assert first.published_date == "2026-09-02"
    assert "The Grammar of Graphics" in first.snippet
    assert "Maintainer: Thomas Lin Pedersen" in first.snippet
    assert "Universe: tidyverse" in first.snippet
    assert "Stars: 6,991" in first.snippet
    assert "Used by: 8,859" in first.snippet
    assert "Topics: data-visualisation, visualisation" in first.snippet
    assert first.extra == {
        "package_name": "ggplot2",
        "title": "Create Elegant Data Visualisations Using the Grammar of Graphics",
        "description": (
            "A system for 'declaratively' creating graphics, based on "
            '"The Grammar of Graphics".'
        ),
        "universe": "tidyverse",
        "maintainer": "Thomas Lin Pedersen",
        "maintainer_login": "thomasp85",
        "stars": 6991,
        "used_by": 8859,
        "topics": ["data-visualisation", "visualisation"],
        "updated": "2026-09-02",
        "page_url": "https://tidyverse.r-universe.dev/ggplot2",
        "cran_url": None,
        "total_results": 3,
    }


def test_parse_cran_package_exposes_cran_url() -> None:
    result = _provider()._parse(_SEARCH_RESPONSE)
    mass = result.results[1]

    assert mass.url == "https://cran.r-universe.dev/MASS"
    assert mass.extra["cran_url"] == "https://cran.r-project.org/package=MASS"
    assert mass.extra["stars"] is None
    assert mass.snippet == (
        "Functions and datasets to support Venables and Ripley. | "
        "Maintainer: Brian Ripley | Universe: cran | Used by: 7,638"
    )


def test_parse_handles_missing_and_malformed_fields() -> None:
    result = _provider()._parse(_SEARCH_RESPONSE)
    alien = result.results[2]

    # No universe means the hit falls back to the r-universe search page.
    assert alien.url == "https://r-universe.dev/search/?q=alienpkg"
    assert alien.published_date is None
    assert alien.extra["universe"] is None
    assert alien.extra["maintainer"] is None
    assert alien.extra["maintainer_login"] is None
    assert alien.extra["stars"] is None
    assert alien.extra["used_by"] is None
    assert alien.extra["topics"] == []
    assert alien.extra["cran_url"] is None
    assert alien.snippet == "A package with no universe metadata"


def test_parse_empty_and_malformed_payloads() -> None:
    p = _provider()
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []
    assert p._parse(None).results == []
    assert p._parse("junk").results == []
    assert p._parse({"results": "junk"}).results == []
    assert p._parse({"results": [{"Package": ""}, 42]}).results == []


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse(_SEARCH_RESPONSE, limit=2).results) == 2
    assert len(p._parse(_SEARCH_RESPONSE, 1).results) == 1


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_queries_index(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE)
    )

    p = _provider()
    result = await p.search("ggplot2", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["ggplot2", "MASS", "alienpkg"]
    call = respx_mock.calls[0]
    assert call.request.url.params["q"] == "ggplot2"
    assert call.request.url.params["limit"] == "5"


@pytest.mark.asyncio
async def test_search_skips_blank_query(respx_mock) -> None:
    route = respx_mock.get(_SEARCH_URL)

    p = _provider()
    result = await p.search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE)
    )

    p = _provider()
    result = await p.search("no-such-r-package-xyz", SearchParams(num_results=5))

    assert result.results == []
