"""Unit tests for the Wiktionary search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.wiktionary import WiktionaryProvider


def _payload() -> dict:
    """A realistic generator=search + prop=revisions API response.

    Note: pages are keyed by pageid (unordered) and carry an ``index`` field
    that encodes search relevance order, which the parser must honor.  Entry
    content is raw wikitext; definitions are ``#`` list items.
    """
    return {
        "query": {
            "pages": {
                "47472": {
                    "pageid": 47472,
                    "index": 1,
                    "title": "serendipity",
                    "revisions": [
                        {
                            "slots": {
                                "main": {
                                    "*": (
                                        "==English==\n"
                                        "===Etymology===\n"
                                        "From {{suffix|en|Serendip|-ity}}.\n"
                                        "===Noun===\n"
                                        "{{en-noun|~}}\n"
                                        "# An unsought, unintended, and/or "
                                        "unexpected, but fortunate, discovery "
                                        "and/or learning experience that "
                                        "happens by accident.\n"
                                        "# {{lb|en|dated}} A combination of "
                                        "events which are not individually "
                                        "beneficial, but occurring together "
                                        "produce a good outcome.\n"
                                    ),
                                },
                            },
                        },
                    ],
                },
                "625296": {
                    "pageid": 625296,
                    "index": 2,
                    "title": "serendipity berry",
                    "revisions": [
                        {
                            "slots": {
                                "main": {
                                    "*": (
                                        "==English==\n"
                                        "===Noun===\n"
                                        "{{en-noun}}\n"
                                        "# The [[fruit]] of a [[West African]] "
                                        "[[vine]] of [[species]] "
                                        "{{taxlink|Dioscoreophyllum cumminsii"
                                        "|species}}, which is the [[source]] "
                                        "of an [[intensely]] [[sweet]] "
                                        "[[substance]], [[monellin]].\n"
                                    ),
                                },
                            },
                        },
                    ],
                },
            },
        },
    }


def _provider() -> WiktionaryProvider:
    return WiktionaryProvider()


def test_parse_basic():
    p = _provider()
    result = p._parse(_payload())

    assert len(result.results) == 2
    # index 1 (serendipity) must come before index 2 (serendipity berry)
    assert result.results[0].title == "serendipity"
    assert result.results[0].url == "https://en.wiktionary.org/wiki/serendipity"
    assert result.results[0].provider == "wiktionary"
    assert result.results[0].rank == 1
    assert result.results[0].source == "en.wiktionary.org"
    assert "fortunate" in result.results[0].snippet
    assert "accident" in result.results[0].snippet
    assert result.results[0].extra["pageid"] == 47472

    assert result.results[1].title == "serendipity berry"
    assert result.results[1].url == ("https://en.wiktionary.org/wiki/serendipity_berry")
    assert result.results[1].rank == 2


def test_snippet_strips_wikitext_markup():
    p = _provider()
    result = p._parse(_payload())
    snippet = result.results[1].snippet
    # Templates, links, and bold markers must be stripped to plain text.
    assert "{{" not in snippet and "}}" not in snippet
    assert "[[" not in snippet and "]]" not in snippet
    assert "fruit" in snippet and "monellin" in snippet


def test_snippet_truncates_long_definitions():
    p = _provider()
    long_definition = "# " + "word " * 300
    payload = {
        "query": {
            "pages": {
                "1": {
                    "pageid": 1,
                    "index": 1,
                    "title": "longword",
                    "revisions": [
                        {
                            "slots": {
                                "main": {
                                    "*": (
                                        f"==English==\n===Noun===\n{long_definition}\n"
                                    ),
                                },
                            },
                        },
                    ],
                },
            },
        },
    }
    result = p._parse(payload)
    assert len(result.results) == 1
    assert len(result.results[0].snippet) <= 400


def test_snippet_skips_redirects_and_empty_lines():
    p = _provider()
    payload = {
        "query": {
            "pages": {
                "1": {
                    "pageid": 1,
                    "index": 1,
                    "title": "Redirected",
                    "revisions": [
                        {
                            "slots": {
                                "main": {"*": "#REDIRECT [[serendipity]]\n"},
                            },
                        },
                    ],
                },
                "2": {
                    "pageid": 2,
                    "index": 2,
                    "title": "Real Entry",
                    "revisions": [
                        {
                            "slots": {
                                "main": {
                                    "*": (
                                        "==English==\n===Noun===\n"
                                        "# A real definition.\n"
                                    ),
                                },
                            },
                        },
                    ],
                },
            },
        },
    }
    result = p._parse(payload)
    assert len(result.results) == 2
    assert result.results[0].title == "Redirected"
    assert result.results[0].snippet == ""
    assert result.results[1].title == "Real Entry"
    assert result.results[1].snippet == "A real definition."


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
                "1": {"pageid": 1, "index": 1, "title": "Valid", "revisions": []},
                "2": {"pageid": 2, "index": 2, "revisions": []},
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

    respx_mock.get("https://en.wiktionary.org/w/api.php").mock(
        return_value=respx.MockResponse(200, json=_payload()),
    )

    p = _provider()
    result = await p.search("serendipity", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "wiktionary"
    assert result.results[0].title == "serendipity"
