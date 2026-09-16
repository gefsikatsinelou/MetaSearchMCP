"""Unit tests for the DOAB open-access book search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.doab import DoabProvider

_SAMPLE_RESPONSE = [
    {
        "uuid": "1dd8d5db-2fa0-4cc7-b991-e103b7320b7e",
        "name": "Confronting Climate Coloniality",
        "handle": "20.500.12854/146789",
        "type": "item",
        "metadata": [
            {"key": "dc.title", "value": "Confronting Climate Coloniality"},
            {
                "key": "dc.title.alternative",
                "value": "Decolonizing Pathways for Climate Justice",
            },
            {"key": "dc.contributor.editor", "value": "Sultana, Farhana"},
            {"key": "dc.date.issued", "value": "2024"},
            {"key": "dc.identifier", "value": "ONIX_20241025_9781003465973_16"},
            {
                "key": "dc.identifier.uri",
                "value": "https://directory.doabooks.org/handle/20.500.12854/146789",
            },
            {
                "key": "dc.description.abstract",
                "value": "A study of climate coloniality.",
            },
            {"key": "dc.language", "value": "English"},
            {
                "key": "dc.relation.ispartofseries",
                "value": "Routledge Advances in Climate Change Research",
            },
            {"key": "dc.rights", "value": "open access"},
            {"key": "dc.subject.other", "value": "climate change"},
            {"key": "dc.subject.other", "value": "climate justice"},
            {"key": "dc.subject.other", "value": "thema EDItEUR::R Earth Sciences::RN"},
            {"key": "dc.type", "value": "book"},
            {"key": "oapen.identifier.doi", "value": "10.4324/9781003465973"},
            {"key": "publisher.name", "value": "Taylor & Francis"},
        ],
    },
    {
        "uuid": "second",
        "name": None,
        "handle": "20.500.12854/99999",
        "metadata": [
            {"key": "dc.title", "value": "  Open   Data  Handbook "},
            {"key": "dc.contributor.author", "value": "Doe, Jane"},
            {"key": "dc.contributor.author", "value": "Doe, Jane"},
            {"key": "dc.identifier.isbn", "value": "978-3-030-12345-6"},
            {"key": "dc.date.issued", "value": "2021-05-01"},
            {"key": "dc.type", "value": "book"},
        ],
    },
    {
        "uuid": "grantor",
        "name": "Byrd Polar and Climate Research Center",
        "handle": "20.500.12854/5363",
        "metadata": [
            {"key": "dc.title", "value": "Byrd Polar and Climate Research Center"},
            {"key": "dc.type", "value": "grantor"},
        ],
    },
    {
        "uuid": "untitled",
        "handle": "20.500.12854/1",
        "metadata": [{"key": "dc.type", "value": "book"}],
    },
    "not-a-dict",
]


def _provider() -> DoabProvider:
    return DoabProvider()


def test_doab_parse_basic():
    result = _provider()._parse(_SAMPLE_RESPONSE, 10, 4181)

    assert [r.title for r in result.results] == [
        "Confronting Climate Coloniality",
        "Open Data Handbook",
    ]
    r = result.results[0]
    assert r.url == "https://doi.org/10.4324/9781003465973"
    assert r.source == "doabooks.org"
    assert r.provider == "doab"
    assert r.rank == 1
    assert r.published_date == "2024"
    assert "A study of climate coloniality." in r.snippet
    assert "Editors: Sultana, Farhana" in r.snippet
    assert "Publisher: Taylor & Francis" in r.snippet
    assert "Year: 2024" in r.snippet
    assert "Language: English" in r.snippet
    assert "thema EDItEUR" not in r.snippet
    assert r.extra["doi"] == "10.4324/9781003465973"
    assert r.extra["isbn"] == ["9781003465973"]
    assert r.extra["editors"] == ["Sultana, Farhana"]
    assert r.extra["authors"] == []
    assert r.extra["subjects"] == ["climate change", "climate justice"]
    assert r.extra["license"] == "open access"
    assert r.extra["handle"] == "20.500.12854/146789"
    assert r.extra["alternative_title"] == "Decolonizing Pathways for Climate Justice"
    assert r.extra["total_results"] == 4181


def test_doab_parse_handle_fallback_and_dedup():
    result = _provider()._parse(_SAMPLE_RESPONSE, 10)
    r = result.results[1]

    assert r.url == "https://directory.doabooks.org/handle/20.500.12854/99999"
    assert r.published_date == "2021"
    assert r.extra["authors"] == ["Doe, Jane"]
    assert r.extra["isbn"] == ["978-3-030-12345-6"]
    assert r.extra["publisher"] == ""
    assert r.extra["doi"] == ""
    assert r.snippet == "Authors: Doe, Jane | Year: 2021"


def test_doab_skips_non_books_and_untitled():
    result = _provider()._parse(_SAMPLE_RESPONSE, 10)
    titles = [r.title for r in result.results]
    assert "Byrd Polar and Climate Research Center" not in titles
    assert len(result.results) == 2


def test_doab_limit_caps_results():
    result = _provider()._parse(_SAMPLE_RESPONSE, 1)
    assert [r.title for r in result.results] == ["Confronting Climate Coloniality"]


def test_doab_parse_non_list_payload():
    assert _provider()._parse({"results": []}, 10).results == []
    assert _provider()._parse(None, 10).results == []


def test_doab_solr_query_sanitizes():
    assert DoabProvider._solr_query("climate policy") == "climate policy"
    assert (
        DoabProvider._solr_query('machine:learning "deep"') == "machine learning deep"
    )
    assert DoabProvider._solr_query("  spaced   out  ") == "spaced out"
    assert DoabProvider._solr_query("::") == ""
    assert DoabProvider._solr_query("") == ""


def test_doab_year_and_isbn_helpers():
    assert DoabProvider._year("2024") == "2024"
    assert DoabProvider._year("2021-05-01") == "2021"
    assert DoabProvider._year("") == ""

    fields = {
        "dc.identifier": ["ONIX_20241025_9781003465973_16"],
        "dc.identifier.isbn": ["978-3-030-12345-6"],
    }
    assert DoabProvider._isbn(fields) == [
        "978-3-030-12345-6",
        "9781003465973",
    ]
    assert DoabProvider._isbn({}) == []


def test_doab_total_header():
    assert DoabProvider._total({"x-total-count": "4181"}) == 4181
    assert DoabProvider._total({"x-total-count": None}) is None
    assert DoabProvider._total({"x-total-count": "many"}) is None
    assert DoabProvider._total(None) is None


def test_doab_is_available():
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_doab_search_hits_api_and_parses(respx_mock):
    import respx

    respx_mock.get(
        "https://directory.doabooks.org/rest/search",
        params={
            "query": "climate AND dc.type:book",
            "limit": "5",
            "expand": "metadata",
        },
    ).mock(
        return_value=respx.MockResponse(
            200,
            json=_SAMPLE_RESPONSE,
            headers={"x-total-count": "4181"},
        ),
    )

    result = await _provider().search("climate", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "doab"
    assert result.results[0].extra["total_results"] == 4181


@pytest.mark.asyncio
async def test_doab_search_blank_query_skips_request(respx_mock):
    """A blank or punctuation-only query never reaches the network."""
    result = await _provider().search("   ", SearchParams(num_results=5))
    assert result.results == []
    result = await _provider().search("::", SearchParams(num_results=5))
    assert result.results == []
