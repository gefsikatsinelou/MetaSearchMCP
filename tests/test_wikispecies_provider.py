"""Unit tests for the Wikispecies search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.wikispecies import WikispeciesProvider


def _payload() -> dict:
    """A realistic generator=search + prop=extracts API response.

    Wikispecies extracts lead with a ``== Taxonavigation ==`` heading
    followed by plain classification lines; the parser must drop headings,
    collapse lines, and honor the page ``index`` (search relevance) field.
    Note: pages are keyed by pageid (unordered).
    """
    return {
        "query": {
            "pages": {
                "9531": {
                    "pageid": 9531,
                    "index": 2,
                    "title": "Panthera leo",
                    "extract": (
                        "\n== Taxonavigation ==\n\n"
                        "Familia: Felidae\n"
                        "Subfamilia: Pantherinae\n"
                        "Genus: Panthera\n"
                        "Species: Panthera leo\n\n"
                        "== Name ==\n"
                        "Panthera leo (Linnaeus, 1758)\n"
                    ),
                },
                "18765": {
                    "pageid": 18765,
                    "index": 1,
                    "title": "Panthera",
                    "extract": (
                        "\n== Taxonavigation ==\n\n"
                        "Familia: Felidae\n"
                        "Subfamilia: Pantherinae\n"
                        "Genus: Panthera\n"
                    ),
                },
            },
        },
    }


def _provider() -> WikispeciesProvider:
    return WikispeciesProvider()


def test_parse_basic():
    p = _provider()
    result = p._parse(_payload())

    assert len(result.results) == 2
    # index 1 (Panthera) must come before index 2 (Panthera leo)
    first = result.results[0]
    assert first.title == "Panthera"
    assert first.url == "https://species.wikimedia.org/wiki/Panthera"
    assert first.provider == "wikispecies"
    assert first.rank == 1
    assert first.source == "species.wikimedia.org"
    assert first.extra["pageid"] == 18765

    second = result.results[1]
    assert second.title == "Panthera leo"
    assert second.url == "https://species.wikimedia.org/wiki/Panthera_leo"
    assert second.rank == 2
    # == headings are dropped, classification lines kept and collapsed
    assert "==" not in second.snippet
    assert "Familia: Felidae | Subfamilia: Pantherinae" in second.snippet
    assert "Panthera leo (Linnaeus, 1758)" in second.snippet
    assert "\n" not in second.snippet


def test_parse_empty():
    p = _provider()
    result = p._parse({"query": {"pages": {}}})
    assert result.results == []


def test_parse_missing_query_block():
    p = _provider()
    assert p._parse({}).results == []
    assert p._parse({"query": {"pages": None}}).results == []


def test_parse_skips_pages_without_title():
    p = _provider()
    payload = {
        "query": {
            "pages": {
                "1": {"pageid": 1, "index": 1, "title": "Felis catus", "extract": "x"},
                "2": {"pageid": 2, "index": 2, "extract": "no title"},
            },
        },
    }
    result = p._parse(payload)
    assert len(result.results) == 1
    assert result.results[0].title == "Felis catus"


def test_clean_snippet_truncates_long_extract():
    p = _provider()
    long_extract = "Line one\nLine two\n" + "word " * 600
    snippet = p._clean_snippet(long_extract)
    assert len(snippet) <= 400
    assert snippet.startswith("Line one | Line two")
    assert p._clean_snippet("") == ""
    assert p._clean_snippet("== Only a heading ==\n") == ""


def test_is_available():
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock):
    import respx

    respx_mock.get("https://species.wikimedia.org/w/api.php").mock(
        return_value=respx.MockResponse(200, json=_payload()),
    )

    p = _provider()
    result = await p.search("panthera", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "wikispecies"
    assert result.results[0].title == "Panthera"
    assert result.results[1].title == "Panthera leo"
