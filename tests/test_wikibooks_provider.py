"""Unit tests for the Wikibooks search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH
from metasearchmcp.providers.wikibooks import WikibooksProvider


def _payload() -> dict:
    """A realistic generator=search + prop=extracts API response.

    Note: pages are keyed by pageid (unordered) and carry an ``index`` field
    that encodes search relevance order, which the parser must honor.
    """
    return {
        "query": {
            "pages": {
                "42116": {
                    "pageid": 42116,
                    "index": 2,
                    "title": "C_Programming/Intro exercise",
                    "extract": (
                        "The C programming language is a general-purpose, "
                        "procedural computer programming language supporting "
                        "structured programming."
                    ),
                },
                "1192": {
                    "pageid": 1192,
                    "index": 1,
                    "title": "Cookbook:Apple Pie",
                    "extract": (
                        "Apple pie is a classic American dessert made with "
                        "apples, sugar, and a flaky pastry crust."
                    ),
                },
            },
        },
    }


def _provider() -> WikibooksProvider:
    return WikibooksProvider()


def test_parse_basic():
    p = _provider()
    result = p._parse(_payload())

    assert len(result.results) == 2
    # index 1 (Cookbook:Apple Pie) must come before index 2 (C Programming)
    assert result.results[0].title == "Cookbook:Apple Pie"
    assert result.results[0].url == ("https://en.wikibooks.org/wiki/Cookbook:Apple_Pie")
    assert result.results[0].provider == "wikibooks"
    assert result.results[0].rank == 1
    assert result.results[0].source == "en.wikibooks.org"
    assert "classic American dessert" in result.results[0].snippet
    assert result.results[0].extra["pageid"] == 1192

    assert result.results[1].title == "C_Programming/Intro exercise"
    assert result.results[1].url == (
        "https://en.wikibooks.org/wiki/C_Programming/Intro_exercise"
    )
    assert result.results[1].rank == 2


def test_parse_preserves_namespace_in_title():
    """Pages in namespaces (e.g. Cookbook:) keep their full title in the URL."""
    p = _provider()
    payload = {
        "query": {
            "pages": {
                "5": {
                    "pageid": 5,
                    "index": 1,
                    "title": "Cookbook:Lasagna",
                    "extract": "Lasagna is a baked Italian pasta dish.",
                },
            },
        },
    }
    result = p._parse(payload)
    assert len(result.results) == 1
    assert result.results[0].title == "Cookbook:Lasagna"
    assert result.results[0].url == ("https://en.wikibooks.org/wiki/Cookbook:Lasagna")


def test_parse_truncates_long_snippets():
    p = _provider()
    payload = {
        "query": {
            "pages": {
                "1": {
                    "pageid": 1,
                    "index": 1,
                    "title": "Long Book",
                    "extract": "x" * (MAX_SNIPPET_LENGTH + 500),
                },
            },
        },
    }
    result = p._parse(payload)
    assert len(result.results) == 1
    assert len(result.results[0].snippet) == MAX_SNIPPET_LENGTH


def test_parse_empty():
    p = _provider()
    result = p._parse({"query": {"pages": {}}})
    assert result.results == []


def test_parse_missing_query_block():
    p = _provider()
    result = p._parse({})
    assert result.results == []


def test_parse_skips_pages_without_title():
    p = _provider()
    payload = {
        "query": {
            "pages": {
                "1": {"pageid": 1, "index": 1, "title": "Valid", "extract": "x"},
                "2": {"pageid": 2, "index": 2, "extract": "no title"},
            },
        },
    }
    result = p._parse(payload)
    assert len(result.results) == 1
    assert result.results[0].title == "Valid"


def test_is_available():
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock):
    import respx

    respx_mock.get("https://en.wikibooks.org/w/api.php").mock(
        return_value=respx.MockResponse(200, json=_payload()),
    )

    p = _provider()
    result = await p.search("apple pie", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "wikibooks"
    assert result.results[0].title == "Cookbook:Apple Pie"
