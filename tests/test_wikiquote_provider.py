"""Unit tests for the Wikiquote search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.wikiquote import WikiquoteProvider


def _payload() -> dict:
    """A realistic generator=search + prop=extracts API response.

    Note: pages are keyed by pageid (unordered) and carry an ``index`` field
    that encodes search relevance order, which the parser must honor.
    """
    return {
        "query": {
            "pages": {
                "46436": {
                    "pageid": 46436,
                    "index": 2,
                    "title": "Monty Python and the Holy Grail",
                    "extract": (
                        "Monty Python and the Holy Grail is a 1975 film about "
                        "King Arthur and his knights who embark on a low-budget "
                        "search for the Grail."
                    ),
                },
                "10921": {
                    "pageid": 10921,
                    "index": 1,
                    "title": "Python",
                    "extract": (
                        "Python is an interpreted, interactive programming "
                        "language created by Guido van Rossum in 1990."
                    ),
                },
            },
        },
    }


def _provider() -> WikiquoteProvider:
    return WikiquoteProvider()


def test_parse_basic():
    p = _provider()
    result = p._parse(_payload())

    assert len(result.results) == 2
    # index 1 (Python) must come before index 2 (Monty Python)
    assert result.results[0].title == "Python"
    assert result.results[0].url == "https://en.wikiquote.org/wiki/Python"
    assert result.results[0].provider == "wikiquote"
    assert result.results[0].rank == 1
    assert result.results[0].source == "en.wikiquote.org"
    assert "Guido van Rossum" in result.results[0].snippet
    assert result.results[0].extra["pageid"] == 10921

    assert result.results[1].title == "Monty Python and the Holy Grail"
    assert result.results[1].url == (
        "https://en.wikiquote.org/wiki/Monty_Python_and_the_Holy_Grail"
    )
    assert result.results[1].rank == 2


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

    respx_mock.get("https://en.wikiquote.org/w/api.php").mock(
        return_value=respx.MockResponse(200, json=_payload()),
    )

    p = _provider()
    result = await p.search("python", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "wikiquote"
    assert result.results[0].title == "Python"
