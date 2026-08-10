"""Unit tests for the Zenodo research data search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.providers.zenodo import ZenodoProvider

_SAMPLE_RESPONSE = {
    "hits": {
        "total": 2,
        "hits": [
            {
                "id": 17306725,
                "links": {
                    "self_html": "https://zenodo.org/records/17306725",
                    "doi": "https://doi.org/10.5281/zenodo.17306725",
                },
                "metadata": {
                    "title": "OQpy: OpenQASM 3 + OpenPulse in Python",
                    "doi": "10.5281/zenodo.17306725",
                    "publication_date": "2025-10-09",
                    "description": (
                        "<h2><span>Abstract</span></h2>\n"
                        "<p><span>A Python library for writing quantum programs "
                        "and pulse schedules.</span></p>"
                    ),
                    "access_right": "open",
                    "creators": [
                        {
                            "name": "Reinhold, Philip",
                            "affiliation": "MIT",
                            "orcid": "0000-0000-0000-0000",
                        },
                        {"name": "Teo, Stephanie"},
                    ],
                    "keywords": ["quantum", "openqasm"],
                    "resource_type": {"title": "Software", "type": "software"},
                    "license": {"id": "apache-2.0"},
                },
            },
            {
                "id": 999,
                "links": {},
                "metadata": {
                    "title": "No URL Record",
                    "description": "This record has no landing page link.",
                },
            },
        ],
    },
}

_EMPTY_RESPONSE = {"hits": {"total": 0, "hits": []}}


def test_zenodo_parse_basic():
    p = ZenodoProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "OQpy: OpenQASM 3 + OpenPulse in Python"
    assert r.url == "https://zenodo.org/records/17306725"
    assert "A Python library for writing quantum programs" in r.snippet
    assert "Creators: Reinhold, Philip, Teo, Stephanie" in r.snippet
    assert "Type: Software" in r.snippet
    assert "Access: open" in r.snippet
    assert r.source == "zenodo.org"
    assert r.provider == "zenodo"
    assert r.rank == 1
    assert r.published_date == "2025-10-09"
    assert r.extra["doi"] == "10.5281/zenodo.17306725"
    assert r.extra["creators"] == ["Reinhold, Philip", "Teo, Stephanie"]
    assert r.extra["resource_type"] == "Software"
    assert r.extra["access_right"] == "open"
    assert r.extra["license"] == "apache-2.0"
    assert r.extra["keywords"] == ["quantum", "openqasm"]


def test_zenodo_parse_skips_item_without_url():
    p = ZenodoProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    # Second item has no landing page link -> skipped.
    assert all(r.url for r in result.results)
    assert len(result.results) == 1


def test_zenodo_parse_empty():
    p = ZenodoProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_zenodo_parse_missing_keys():
    p = ZenodoProvider()
    result = p._parse(
        {
            "hits": {
                "hits": [
                    {
                        "links": {"self_html": "https://zenodo.org/records/1"},
                        "metadata": {
                            "title": "Lonely Record",
                            "creators": None,
                            "resource_type": None,
                            "access_right": None,
                        },
                    },
                ],
            },
        },
    )
    r = result.results[0]
    assert r.snippet == ""
    assert r.published_date is None
    assert r.extra["doi"] == ""
    assert r.extra["creators"] == []
    assert r.extra["resource_type"] == ""
    assert r.extra["access_right"] == ""
    assert r.extra["license"] == ""
    assert r.extra["keywords"] == []


def test_zenodo_landing_url_fallbacks():
    assert (
        ZenodoProvider._landing_url(
            {
                "links": {
                    "self_html": "https://zenodo.org/records/1",
                    "self_doi_html": "https://zenodo.org/doi/10.5281/zenodo.1",
                },
            },
        )
        == "https://zenodo.org/records/1"
    )
    assert (
        ZenodoProvider._landing_url(
            {"links": {"self_html": "", "self_doi_html": "https://zenodo.org/doi/1"}},
        )
        == "https://zenodo.org/doi/1"
    )
    assert ZenodoProvider._landing_url({"links": {}}) == ""
    assert ZenodoProvider._landing_url({}) == ""


def test_zenodo_creator_names():
    assert ZenodoProvider._creator_names(
        [
            {"name": "  Alice  Smith "},
            {"name": "Bob"},
            {"name": ""},
            "not-a-dict",
        ]
    ) == ["Alice Smith", "Bob"]
    assert ZenodoProvider._creator_names([]) == []
    assert ZenodoProvider._creator_names(None) == []
    assert ZenodoProvider._creator_names("not-a-list") == []


def test_zenodo_strip_html():
    assert ZenodoProvider._strip_html("<p><b>Hi</b> there</p>") == "Hi there"
    assert ZenodoProvider._strip_html("") == ""
    assert ZenodoProvider._strip_html(None) == ""


def test_zenodo_is_available():
    """Keyless provider is always available."""
    assert ZenodoProvider().is_available() is True


@pytest.mark.asyncio
async def test_zenodo_search_builds_query(respx_mock):
    """The search method hits the records endpoint and parses the response."""
    import respx

    respx_mock.get("https://zenodo.org/api/records").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    from metasearchmcp.contracts import SearchParams

    p = ZenodoProvider()
    result = await p.search("quantum computing", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "zenodo"
