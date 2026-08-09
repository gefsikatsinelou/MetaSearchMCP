"""Unit tests for the Marginalia search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.marginalia import MarginaliaProvider


def _sample_response() -> dict:
    return {
        "license": "CC-BY-NC-SA 4.0",
        "page": 1,
        "pages": 4,
        "query": "bitcoin",
        "results": [
            {
                "url": "https://en.wikipedia.org/wiki/Bitcoin",
                "title": "Bitcoin",
                "description": "Bitcoin is the first decentralized cryptocurrency.",
                "quality": 3.5381696920225694,
                "format": "html",
                "resultsFromDomain": 1348,
                "details": [[]],
            },
            {
                "url": "https://example.org/blog/bitcoin",
                "title": "A Personal Bitcoin Blog",
                "description": "Notes from a hobbyist miner.",
                "quality": 2.1,
                "format": "html",
                "resultsFromDomain": 5,
                "details": [[]],
            },
            {
                "url": "https://broken.example/no-title",
                "title": "",
                "description": "No title here",
                "quality": 1.0,
                "format": "html",
                "resultsFromDomain": 1,
                "details": [[]],
            },
        ],
    }


def test_parse_basic():
    p = MarginaliaProvider()
    result = p._parse(_sample_response())

    assert len(result.results) == 2  # item without title is skipped
    r = result.results[0]
    assert r.title == "Bitcoin"
    assert r.url == "https://en.wikipedia.org/wiki/Bitcoin"
    assert r.provider == "marginalia"
    assert r.source == "marginalia.nu"
    assert r.rank == 1
    assert "decentralized" in r.snippet
    assert r.extra["quality"] == 3.54
    assert r.extra["pages_from_domain"] == 1348


def test_parse_second_result_rank():
    p = MarginaliaProvider()
    result = p._parse(_sample_response())
    assert result.results[1].rank == 2
    assert result.results[1].extra["pages_from_domain"] == 5


def test_parse_empty():
    p = MarginaliaProvider()
    result = p._parse({"results": []})
    assert result.results == []


def test_parse_missing_results_key():
    p = MarginaliaProvider()
    result = p._parse({})
    assert result.results == []


def test_parse_skips_non_dict_items():
    p = MarginaliaProvider()
    result = p._parse({"results": ["not-a-dict", None]})
    assert result.results == []


def test_is_available():
    """Keyless provider is always available."""
    assert MarginaliaProvider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock):
    import respx

    respx_mock.get(
        "https://api.marginalia.nu/public/search/bitcoin",
        params={"count": "5"},
    ).mock(
        return_value=respx.MockResponse(200, json=_sample_response()),
    )

    p = MarginaliaProvider()
    result = await p.search("bitcoin", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "marginalia"
    assert result.results[0].title == "Bitcoin"
