"""Unit tests for the GDELT news search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.gdelt import GDELTProvider

_SAMPLE_RESPONSE = {
    "articles": [
        {
            "url": "https://finance.yahoo.com/healthcare/articles/crispr-therapeutics.html",
            "title": "Has CRISPR Therapeutics Fallen Far Enough To Look Undervalued?",
            "seendate": "20260718T090000Z",
            "domain": "finance.yahoo.com",
            "language": "English",
            "sourcecountry": "United States",
        },
        {
            "url": "https://www.nutraingredients.com/Article/2026/06/15/from-bench-to-biome/",
            "title": (
                "From bench to biome: CRISPR phages could precision edit the microbiome"
            ),
            "seendate": "20260615T154500Z",
            "domain": "nutraingredients.com",
            "language": "English",
            "sourcecountry": "United Kingdom",
        },
        {
            # Missing title -> skipped.
            "url": "https://example.com/untitled",
            "seendate": "20260701T000000Z",
            "domain": "example.com",
        },
    ]
}

_EMPTY_RESPONSE = {"articles": []}


def _provider() -> GDELTProvider:
    return GDELTProvider()


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Has CRISPR Therapeutics Fallen Far Enough To Look Undervalued?"
    assert (
        r.url
        == "https://finance.yahoo.com/healthcare/articles/crispr-therapeutics.html"
    )
    assert "Source: finance.yahoo.com" in r.snippet
    assert "Language: English" in r.snippet
    assert "Country: United States" in r.snippet
    assert r.source == "finance.yahoo.com"
    assert r.provider == "gdelt"
    assert r.rank == 1
    assert r.published_date == "2026-07-18"
    assert r.extra["domain"] == "finance.yahoo.com"
    assert r.extra["language"] == "English"
    assert r.extra["source_country"] == "United States"
    assert r.extra["seendate"] == "20260718T090000Z"


def test_parse_second_result() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    r = result.results[1]
    assert r.source == "nutraingredients.com"
    assert r.published_date == "2026-06-15"
    assert r.rank == 2


def test_parse_skips_articles_missing_title_or_url() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert all(r.title for r in result.results)
    assert all(r.url for r in result.results)


def test_parse_empty() -> None:
    result = _provider()._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_parse_non_dict_articles_skipped() -> None:
    result = _provider()._parse({"articles": ["not-a-dict", None, 42]})
    assert result.results == []


def test_parse_seendate() -> None:
    p = _provider()
    assert p._parse_seendate("20260718T090000Z") == "2026-07-18"
    assert p._parse_seendate("20260718") == "2026-07-18"
    assert p._parse_seendate("") is None
    assert p._parse_seendate(None) is None
    assert p._parse_seendate("garbage") is None


def test_clean_text() -> None:
    p = _provider()
    assert p._clean_text("  a\n  b\t ") == "a b"
    assert p._clean_text(None) == ""
    assert p._clean_text("") == ""


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_builds_query(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.gdeltproject.org/api/v2/doc/doc").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("crispr", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "gdelt"
    request = respx_mock.calls.last.request
    assert request.url.params["query"] == "crispr"
    assert request.url.params["mode"] == "artlist"
    assert request.url.params["format"] == "json"
    assert request.url.params["maxrecords"] == "5"
