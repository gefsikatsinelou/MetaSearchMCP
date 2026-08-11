"""Unit tests for the Google Patents (patent search) provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.google_patents import GooglePatentsProvider

_SAMPLE_RESPONSE = {
    "results": {
        "total_num_results": 3,
        "cluster": [
            {
                "result": [
                    {
                        "id": "patent/JP7463436B2/en",
                        "rank": 0,
                        "patent": {
                            "title": "<b>CRISPR</b>-Cas Systems and Methods for "
                            "Altering Expression of Gene Products",
                            "snippet": "1. An isolated eukaryotic host cell "
                            "comprising an engineered <b>CRISPR</b>-Cas system.",
                            "priority_date": "2012-12-12",
                            "filing_date": "2022-06-14",
                            "grant_date": "2024-04-08",
                            "publication_date": "2024-04-08",
                            "inventor": "Feng Zhang",
                            "assignee": "The Broad Institute",
                            "publication_number": "JP7463436B2",
                            "language": "en",
                        },
                    },
                    {
                        "id": "patent/US10123456B2/en",
                        "rank": 1,
                        "patent": {
                            "title": "Solar cell with improved efficiency",
                            "snippet": "A photovoltaic device comprising ...",
                            "priority_date": "2018-05-01",
                            "filing_date": "2019-04-30",
                            "grant_date": "2020-11-10",
                            "publication_date": "2020-11-10",
                            "inventor": "Jane Doe",
                            "assignee": "",
                            "publication_number": "US10123456B2",
                            "language": "en",
                        },
                    },
                    {
                        # Missing publication_number -> skipped.
                        "id": "patent/XX/bad",
                        "rank": 2,
                        "patent": {"title": "No number here"},
                    },
                ]
            }
        ],
    }
}

_EMPTY_RESPONSE = {"results": {"cluster": [{"result": []}]}}


def _provider() -> GooglePatentsProvider:
    return GooglePatentsProvider()


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert (
        r.title
        == "CRISPR-Cas Systems and Methods for Altering Expression of Gene Products"
    )
    assert r.url == "https://patents.google.com/patent/JP7463436B2/en"
    assert "CRISPR-Cas system" in r.snippet
    assert "Inventors: Feng Zhang" in r.snippet
    assert "Assignee: The Broad Institute" in r.snippet
    assert r.source == "patents.google.com"
    assert r.provider == "google_patents"
    assert r.rank == 1
    assert r.published_date == "2024-04-08"
    assert r.extra["publication_number"] == "JP7463436B2"
    assert r.extra["inventors"] == "Feng Zhang"
    assert r.extra["assignee"] == "The Broad Institute"
    assert r.extra["language"] == "en"
    assert r.extra["filing_date"] == "2022-06-14"
    assert r.extra["priority_date"] == "2012-12-12"


def test_parse_second_result_without_assignee() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    r = result.results[1]
    assert r.url == "https://patents.google.com/patent/US10123456B2/en"
    assert r.rank == 2
    assert "Assignee" not in r.snippet
    assert "Inventors: Jane Doe" in r.snippet


def test_parse_empty() -> None:
    result = _provider()._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_parse_missing_patent_object() -> None:
    result = _provider()._parse({"results": {"cluster": [{"result": [{"id": "x"}]}]}})
    assert result.results == []


def test_parse_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, max_results=1)
    assert len(result.results) == 1
    assert result.results[0].rank == 1


def test_clean_html_strips_tags_and_entities() -> None:
    p = _provider()
    assert p._clean_html("<b>CRISPR</b>-Cas &amp; more") == "CRISPR-Cas & more"
    assert p._clean_html(None) == ""
    assert p._clean_html("") == ""


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_builds_query(respx_mock) -> None:
    import respx

    respx_mock.get("https://patents.google.com/xhr/query").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("crispr", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "google_patents"
    request = respx_mock.calls.last.request
    assert request.url.params["url"] == "q=crispr"
    assert request.url.params["exp"] == ""
