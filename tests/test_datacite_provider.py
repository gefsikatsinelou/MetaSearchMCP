"""Unit tests for the DataCite research dataset search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.datacite import DataCiteProvider

_SAMPLE_ATTRIBUTES: dict[str, object] = {
    "doi": "10.3929/ethz-c-000797458",
    "titles": [{"title": "Example research dataset"}],
    "creators": [{"name": "Doe, Jane"}, {"name": "Smith, John"}],
    "publisher": "Example Data Center",
    "publicationYear": 2025,
    "descriptions": [
        {
            "descriptionType": "Abstract",
            "description": "An example description of the dataset.",
        }
    ],
    "url": "https://doi.org/10.3929/ethz-c-000797458",
    "types": {"resourceTypeGeneral": "Dataset", "resourceType": "Dataset"},
}

_SAMPLE_RESPONSE: dict[str, object] = {
    "data": [
        {
            "id": "10.3929/ethz-c-000797458",
            "type": "dois",
            "attributes": _SAMPLE_ATTRIBUTES,
        }
    ]
}

_EMPTY_RESPONSE: dict[str, object] = {"data": []}


def test_datacite_parse_basic():
    p = DataCiteProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Example research dataset"
    assert r.url == "https://doi.org/10.3929/ethz-c-000797458"
    assert "example description" in r.snippet
    assert "Type: Dataset" in r.snippet
    assert "Publisher: Example Data Center" in r.snippet
    assert "Doe, Jane" in r.snippet
    assert r.source == "datacite.org"
    assert r.provider == "datacite"
    assert r.rank == 1
    assert r.published_date == "2025"
    assert r.extra["doi"] == "10.3929/ethz-c-000797458"
    assert r.extra["creators"] == ["Doe, Jane", "Smith, John"]
    assert r.extra["resource_type"] == "Dataset"
    assert r.extra["publisher"] == "Example Data Center"
    assert r.extra["year"] == "2025"
    assert "example description" in r.extra["abstract"]


def test_datacite_parse_falls_back_to_doi_url():
    p = DataCiteProvider()
    attributes = dict(_SAMPLE_ATTRIBUTES)
    attributes["url"] = ""
    result = p._parse({"data": [{"attributes": attributes}]})
    assert result.results[0].url == "https://doi.org/10.3929/ethz-c-000797458"


def test_datacite_parse_skips_item_without_title_or_doi():
    p = DataCiteProvider()
    result = p._parse(
        {
            "data": [
                {"attributes": {"doi": "10.1/x", "titles": []}},
                {"attributes": {"doi": "", "titles": [{"title": "No DOI"}]}},
            ]
        }
    )
    assert result.results == []


def test_datacite_parse_empty():
    p = DataCiteProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_datacite_parse_non_dict():
    p = DataCiteProvider()
    assert p._parse([{"attributes": {}}]).results == []
    assert p._parse(None).results == []
    assert p._parse({"data": {"not": "a list"}}).results == []


def test_datacite_parse_handles_missing_optional_fields():
    p = DataCiteProvider()
    attributes = {
        "doi": "10.1000/xyz123",
        "titles": [{"title": "Minimal record"}],
    }
    result = p._parse({"data": [{"attributes": attributes}]})
    r = result.results[0]
    assert r.url == "https://doi.org/10.1000/xyz123"
    assert r.snippet == ""
    assert r.published_date is None
    assert r.extra["creators"] == []
    assert r.extra["resource_type"] == ""


def test_datacite_parse_skips_non_dict_items():
    p = DataCiteProvider()
    result = p._parse({"data": ["junk", 42, {"attributes": _SAMPLE_ATTRIBUTES}]})
    assert len(result.results) == 1


def test_datacite_clean_text():
    assert DataCiteProvider._clean_text("  a\n  b  ") == "a b"
    assert DataCiteProvider._clean_text(None) == ""
    assert DataCiteProvider._clean_text("") == ""


def test_datacite_is_available():
    """Keyless provider is always available."""
    assert DataCiteProvider().is_available() is True


@pytest.mark.asyncio
async def test_datacite_search_hits_api_and_parses(respx_mock):
    """The search method hits the DOI endpoint and parses the response."""
    import respx

    respx_mock.get("https://api.datacite.org/dois").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = DataCiteProvider()
    result = await p.search("crispr", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "datacite"
    assert result.results[0].title == "Example research dataset"


@pytest.mark.asyncio
async def test_datacite_search_empty_response(respx_mock):
    """An empty data list yields no results."""
    import respx

    respx_mock.get("https://api.datacite.org/dois").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = DataCiteProvider()
    result = await p.search("zzz", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_datacite_search_truncates_to_limit(respx_mock):
    """The search method truncates results to the requested limit."""
    import respx

    many = {
        "data": [
            {
                "id": f"10.1000/{i}",
                "attributes": {
                    "doi": f"10.1000/{i}",
                    "titles": [{"title": f"Record {i}"}],
                },
            }
            for i in range(1, 6)
        ]
    }
    respx_mock.get("https://api.datacite.org/dois").mock(
        return_value=respx.MockResponse(200, json=many),
    )

    p = DataCiteProvider()
    result = await p.search("data", SearchParams(num_results=2))

    assert len(result.results) == 2
    assert result.results[0].title == "Record 1"


@pytest.mark.asyncio
async def test_datacite_search_passes_query_param(respx_mock):
    """The search method forwards the query as the query parameter."""
    import respx

    route = respx_mock.get("https://api.datacite.org/dois").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = DataCiteProvider()
    await p.search("open data", SearchParams(num_results=3))

    request = route.calls.last.request
    assert request.url.params["query"] == "open data"
    assert request.url.params["page[size]"] == "3"
