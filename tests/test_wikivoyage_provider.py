"""Unit tests for the Wikivoyage search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH
from metasearchmcp.providers.wikivoyage import WikivoyageProvider


def _payload() -> dict:
    """A realistic generator=search + prop=extracts API response.

    Note: pages are keyed by pageid (unordered) and carry an ``index`` field
    that encodes search relevance order, which the parser must honor.
    """
    return {
        "query": {
            "pages": {
                "8644": {
                    "pageid": 8644,
                    "index": 2,
                    "title": "Tokyo",
                    "extract": (
                        "Tokyo is the massive, sprawling capital of Japan, "
                        "and the world's most populous metropolitan area."
                    ),
                },
                "4183": {
                    "pageid": 4183,
                    "index": 1,
                    "title": "Japan",
                    "extract": (
                        "Japan is a country in East Asia, an archipelago "
                        "stretching along the Pacific coast of Asia."
                    ),
                },
            },
        },
    }


def _provider() -> WikivoyageProvider:
    return WikivoyageProvider()


def test_parse_basic():
    p = _provider()
    result = p._parse(_payload())

    assert len(result.results) == 2
    # index 1 (Japan) must come before index 2 (Tokyo)
    assert result.results[0].title == "Japan"
    assert result.results[0].url == "https://en.wikivoyage.org/wiki/Japan"
    assert result.results[0].provider == "wikivoyage"
    assert result.results[0].rank == 1
    assert result.results[0].source == "en.wikivoyage.org"
    assert "archipelago" in result.results[0].snippet
    assert result.results[0].extra["pageid"] == 4183

    assert result.results[1].title == "Tokyo"
    assert result.results[1].url == "https://en.wikivoyage.org/wiki/Tokyo"
    assert result.results[1].rank == 2


def test_parse_truncates_long_snippets():
    p = _provider()
    payload = {
        "query": {
            "pages": {
                "1": {
                    "pageid": 1,
                    "index": 1,
                    "title": "Long Guide",
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

    respx_mock.get("https://en.wikivoyage.org/w/api.php").mock(
        return_value=respx.MockResponse(200, json=_payload()),
    )

    p = _provider()
    result = await p.search("japan", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "wikivoyage"
    assert result.results[0].title == "Japan"
