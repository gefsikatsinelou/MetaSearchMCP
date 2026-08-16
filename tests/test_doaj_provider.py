"""Unit tests for the DOAJ open-access article search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.doaj import DoajProvider

_SAMPLE_RESPONSE = {
    "total": 2,
    "page": 1,
    "pageSize": 2,
    "results": [
        {
            "id": "0002c68cd0644a0f9f98ecd0f85ac2f3",
            "bibjson": {
                "title": "RESTful API Implementation in Making a Master Data Planogram",
                "year": 2020,
                "abstract": (
                    "A retail case study implementing a RESTful API with Flask."
                ),
                "identifier": [
                    {"id": "10.25126/jitecs.202053189", "type": "doi"},
                    {"id": "2540-9433", "type": "pissn"},
                ],
                "link": [
                    {
                        "content_type": "HTML",
                        "type": "fulltext",
                        "url": "https://jitecs.ub.ac.id/index.php/jitecs/article/view/189",
                    },
                ],
                "journal": {
                    "title": (
                        "JITeCS (Journal of Information Technology and "
                        "Computer Science)"
                    ),
                },
                "author": [
                    {"name": "Era Susanti", "affiliation": "Satya Wacana University"},
                    {"name": "Evangs Mailoa", "affiliation": "Satya Wacana University"},
                ],
            },
        },
        {
            "id": "no-link-work",
            "bibjson": {
                "title": "DOI Landing Only",
                "year": 2019,
                "identifier": [{"id": "10.1000/xyz", "type": "doi"}],
            },
        },
    ],
}

_EMPTY_RESPONSE = {"total": 0, "page": 1, "pageSize": 10, "results": []}


def _provider() -> DoajProvider:
    return DoajProvider()


def test_doaj_parse_basic():
    p = _provider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "RESTful API Implementation in Making a Master Data Planogram"
    assert r.url == "https://jitecs.ub.ac.id/index.php/jitecs/article/view/189"
    assert "Journal: JITeCS (Journal of Information Technology" in r.snippet
    assert "Year: 2020" in r.snippet
    assert "Authors: Era Susanti, Evangs Mailoa" in r.snippet
    assert r.source == "doaj.org"
    assert r.provider == "doaj"
    assert r.rank == 1
    assert r.published_date == "2020"
    assert r.extra["doi"] == "10.25126/jitecs.202053189"
    assert r.extra["journal"].startswith("JITeCS")
    assert r.extra["authors"] == ["Era Susanti", "Evangs Mailoa"]
    assert "Flask" in r.extra["abstract"]


def test_doaj_parse_doi_fallback_url():
    p = _provider()
    result = p._parse(_SAMPLE_RESPONSE)

    r = result.results[1]
    assert r.title == "DOI Landing Only"
    assert r.url == "https://doi.org/10.1000/xyz"
    assert r.snippet == "Year: 2019"
    assert r.extra["journal"] == ""
    assert r.extra["authors"] == []


def test_doaj_parse_empty():
    p = _provider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_doaj_parse_missing_fields():
    p = _provider()
    result = p._parse(
        {
            "results": [
                {
                    "id": "x",
                    "bibjson": {
                        "title": "  Lonely  Work ",
                        "identifier": [],
                        "link": [{"type": "fulltext", "url": "https://ex.org/paper"}],
                        "journal": None,
                        "author": None,
                        "abstract": "   spaced\n abstract ",
                    },
                },
                {"id": "y", "bibjson": {"title": "No URL"}},
                {"id": "z", "bibjson": {}},
                {"id": "w", "not_bibjson": True},
            ],
        },
    )
    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Lonely Work"
    assert r.url == "https://ex.org/paper"
    assert r.snippet == ""
    assert r.published_date is None
    assert r.extra["year"] == ""
    assert r.extra["abstract"] == "spaced abstract"


def test_doaj_clean_text():
    assert DoajProvider._clean_text("  a\n  b ") == "a b"
    assert DoajProvider._clean_text("") == ""
    assert DoajProvider._clean_text(None) == ""


def test_doaj_author_list():
    assert DoajProvider._author_list(
        [{"name": "  Alice  Smith "}, {"name": "Bob"}, {"name": ""}],
    ) == ["Alice Smith", "Bob"]
    assert DoajProvider._author_list([]) == []
    assert DoajProvider._author_list(None) == []
    assert DoajProvider._author_list("not-a-list") == []


def test_doaj_doi():
    assert (
        DoajProvider._doi(
            [
                {"id": "2540-9433", "type": "pissn"},
                {"id": "10.1000/abc", "type": "doi"},
            ],
        )
        == "10.1000/abc"
    )
    assert DoajProvider._doi([]) == ""
    assert DoajProvider._doi(None) == ""


def test_doaj_is_available():
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_doaj_search_hits_api_and_parses(respx_mock):
    import respx

    respx_mock.get(
        "https://doaj.org/api/search/articles/python",
        params={"pageSize": "5"},
    ).mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("python", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "doaj"
    assert result.results[0].title.startswith("RESTful API")
