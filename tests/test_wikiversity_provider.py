"""Unit tests for the Wikiversity search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH
from metasearchmcp.providers.wikiversity import WikiversityProvider


def _payload() -> dict:
    """A realistic generator=search + prop=extracts API response.

    Note: pages are keyed by pageid (unordered) and carry an ``index`` field
    that encodes search relevance order, which the parser must honor.
    """
    return {
        "query": {
            "pages": {
                "216741": {
                    "pageid": 216741,
                    "index": 2,
                    "title": "Python",
                    "extract": (
                        "Python is a widely used high-level, general-purpose, "
                        "interpreted, dynamic programming language."
                    ),
                },
                "57887": {
                    "pageid": 57887,
                    "index": 1,
                    "title": "Python Concepts/Why learn Python",
                    "extract": (
                        "Python is one of the easiest programming languages "
                        "to learn for beginners."
                    ),
                },
            },
        },
    }


def _provider() -> WikiversityProvider:
    return WikiversityProvider()


def test_parse_basic():
    p = _provider()
    result = p._parse(_payload())

    assert len(result.results) == 2
    # index 1 must come before index 2
    assert result.results[0].title == "Python Concepts/Why learn Python"
    assert result.results[0].url == (
        "https://en.wikiversity.org/wiki/Python_Concepts/Why_learn_Python"
    )
    assert result.results[0].provider == "wikiversity"
    assert result.results[0].rank == 1
    assert result.results[0].source == "en.wikiversity.org"
    assert "easiest programming languages" in result.results[0].snippet
    assert result.results[0].extra["pageid"] == 57887

    assert result.results[1].title == "Python"
    assert result.results[1].url == "https://en.wikiversity.org/wiki/Python"
    assert result.results[1].rank == 2


def test_parse_truncates_long_snippets():
    p = _provider()
    payload = {
        "query": {
            "pages": {
                "1": {
                    "pageid": 1,
                    "index": 1,
                    "title": "Long Course",
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

    respx_mock.get("https://en.wikiversity.org/w/api.php").mock(
        return_value=respx.MockResponse(200, json=_payload()),
    )

    p = _provider()
    result = await p.search("python", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "wikiversity"
    assert result.results[0].title == "Python Concepts/Why learn Python"
