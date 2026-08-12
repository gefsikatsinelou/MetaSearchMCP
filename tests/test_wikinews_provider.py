"""Unit tests for the Wikinews search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.wikinews import WikinewsProvider


def _payload() -> dict:
    """A realistic generator=search + prop=extracts API response.

    Note: pages are keyed by pageid (unordered) and carry an ``index`` field
    that encodes search relevance order, which the parser must honor.
    Wikinews extracts begin with the article's publication date line.
    """
    return {
        "query": {
            "pages": {
                "139216": {
                    "pageid": 139216,
                    "index": 2,
                    "title": "400 pound python seized by wildlife officials in Florida",
                    "extract": (
                        'Sunday, September 13, 2009\n \nA "monster" Burmese '
                        "python, weighing in at 400 pounds and stretching 18 "
                        "feet long, was seized by Florida wildlife officials."
                    ),
                },
                "2950435": {
                    "pageid": 2950435,
                    "index": 1,
                    "title": "Python 3.12 released",
                    "extract": (
                        "Saturday, June 25, 2022\n \nThe Python Software "
                        "Foundation announced the release of Python 3.12."
                    ),
                },
            },
        },
    }


def _provider() -> WikinewsProvider:
    return WikinewsProvider()


def test_parse_basic():
    p = _provider()
    result = p._parse(_payload())

    assert len(result.results) == 2
    # index 1 (Python 3.12) must come before index 2 (400 pound python)
    assert result.results[0].title == "Python 3.12 released"
    assert result.results[0].url == "https://en.wikinews.org/wiki/Python_3.12_released"
    assert result.results[0].provider == "wikinews"
    assert result.results[0].rank == 1
    assert result.results[0].source == "en.wikinews.org"
    assert result.results[0].published_date == "2022-06-25"
    assert "Python Software Foundation" in result.results[0].snippet
    assert result.results[0].extra["pageid"] == 2950435

    assert result.results[1].title == (
        "400 pound python seized by wildlife officials in Florida"
    )
    assert result.results[1].url == (
        "https://en.wikinews.org/wiki/"
        "400_pound_python_seized_by_wildlife_officials_in_Florida"
    )
    assert result.results[1].rank == 2
    assert result.results[1].published_date == "2009-09-13"


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


def test_extract_published_date_variants():
    p = _provider()
    assert (
        p._extract_published_date("Sunday, September 13, 2009\n body") == "2009-09-13"
    )
    # Format without weekday name.
    assert p._extract_published_date("September 13, 2009\n body") == "2009-09-13"
    # Non-date first line -> None.
    assert p._extract_published_date("Breaking news!\n body") is None
    assert p._extract_published_date("") is None


def test_is_available():
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock):
    import respx

    respx_mock.get("https://en.wikinews.org/w/api.php").mock(
        return_value=respx.MockResponse(200, json=_payload()),
    )

    p = _provider()
    result = await p.search("python", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "wikinews"
    assert result.results[0].title == "Python 3.12 released"
    assert result.results[0].published_date == "2022-06-25"
