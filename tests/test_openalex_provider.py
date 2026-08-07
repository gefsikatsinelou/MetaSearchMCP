"""Unit tests for the OpenAlex scholarly search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.providers.openalex import OpenAlexProvider

_SAMPLE_RESPONSE = {
    "meta": {"count": 2, "per_page": 2},
    "results": [
        {
            "display_name": "Scikit-learn: Machine Learning in Python",
            "doi": "https://doi.org/10.48550/arxiv.1201.0490",
            "publication_date": "2012-01-02",
            "type": "preprint",
            "language": "en",
            "cited_by_count": 63897,
            "primary_location": {
                "landing_page_url": "http://arxiv.org/abs/1201.0490",
                "source": {"display_name": "arXiv (Cornell University)"},
            },
            "authorships": [
                {
                    "author": {
                        "display_name": "Fabian Pedregosa",
                    },
                },
                {
                    "author": {
                        "display_name": "Gael Varoquaux",
                    },
                },
            ],
            "open_access": {"is_oa": True},
        },
        {
            "display_name": "No URL Work",
            "doi": "",
            "primary_location": None,
            "type": "article",
            "cited_by_count": 0,
        },
    ],
}

_EMPTY_RESPONSE = {"meta": {"count": 0}, "results": []}


def test_openalex_parse_basic():
    p = OpenAlexProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Scikit-learn: Machine Learning in Python"
    assert r.url == "http://arxiv.org/abs/1201.0490"
    assert "Authors: Fabian Pedregosa, Gael Varoquaux" in r.snippet
    assert "Venue: arXiv (Cornell University)" in r.snippet
    assert "Cited by: 63897" in r.snippet
    assert "Type: preprint" in r.snippet
    assert r.source == "openalex.org"
    assert r.provider == "openalex"
    assert r.rank == 1
    assert r.published_date == "2012-01-02"
    assert r.extra["doi"] == "https://doi.org/10.48550/arxiv.1201.0490"
    assert r.extra["venue"] == "arXiv (Cornell University)"
    assert r.extra["authors"] == ["Fabian Pedregosa", "Gael Varoquaux"]
    assert r.extra["cited_by_count"] == 63897
    assert r.extra["work_type"] == "preprint"
    assert r.extra["language"] == "en"
    assert r.extra["open_access"] is True


def test_openalex_parse_skips_item_without_url_and_title():
    p = OpenAlexProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    # Second item has no URL and no title -> skipped.
    assert all(r.url for r in result.results)
    assert all(r.title for r in result.results)


def test_openalex_parse_empty():
    p = OpenAlexProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_openalex_parse_missing_keys():
    p = OpenAlexProvider()
    result = p._parse(
        {
            "results": [
                {
                    "display_name": "Lonely Work",
                    "doi": "https://doi.org/10.1000/xyz",
                    "primary_location": None,
                },
            ],
        },
    )
    r = result.results[0]
    assert r.url == "https://doi.org/10.1000/xyz"
    assert r.snippet == ""
    assert r.published_date is None
    assert r.extra["venue"] == ""
    assert r.extra["authors"] == []
    assert r.extra["cited_by_count"] == 0
    assert r.extra["open_access"] is False


def test_openalex_parse_doi_fallback_url():
    p = OpenAlexProvider()
    result = p._parse(
        {
            "results": [
                {
                    "display_name": "DOI Only",
                    "doi": "https://doi.org/10.1000/abc",
                    "primary_location": {"landing_page_url": ""},
                },
            ],
        },
    )
    assert result.results[0].url == "https://doi.org/10.1000/abc"


def test_openalex_author_list():
    assert OpenAlexProvider._author_list(
        [
            {"author": {"display_name": "  Alice  Smith "}},
            {"author": {"display_name": "Bob"}},
        ]
    ) == ["Alice Smith", "Bob"]
    assert OpenAlexProvider._author_list([]) == []
    assert OpenAlexProvider._author_list(None) == []
    assert OpenAlexProvider._author_list("not-a-list") == []


def test_openalex_clean_text():
    assert OpenAlexProvider._clean_text("  a\n  b ") == "a b"
    assert OpenAlexProvider._clean_text("") == ""
    assert OpenAlexProvider._clean_text(None) == ""


def test_openalex_is_available():
    """Keyless provider is always available."""
    assert OpenAlexProvider().is_available() is True


@pytest.mark.asyncio
async def test_openalex_search_builds_query(respx_mock):
    """The search method hits the works endpoint and parses the response."""
    import respx

    respx_mock.get("https://api.openalex.org/works").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    from metasearchmcp.contracts import SearchParams

    p = OpenAlexProvider()
    result = await p.search("machine learning", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "openalex"
