"""Unit tests for the GBIF species search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.gbif import GBIFSpeciesProvider

_SAMPLE_RESPONSE: dict[str, object] = {
    "count": 3,
    "results": [
        {
            "key": 5219404,
            "scientificName": "Panthera leo",
            "canonicalName": "Panthera leo",
            "rank": "SPECIES",
            "taxonomicStatus": "ACCEPTED",
            "kingdom": "Animalia",
            "phylum": "Chordata",
            "class": "Mammalia",
            "order": "Carnivora",
            "family": "Felidae",
            "genus": "Panthera",
            "synonym": False,
            "threatStatuses": ["VULNERABLE"],
            "numOccurrences": 12345,
            "vernacularNames": [
                {"vernacularName": "African lion", "language": "eng"},
                {"vernacularName": "Lion", "language": "eng"},
            ],
        },
        {
            "key": 2490109,
            "scientificName": "Frangula",
            "canonicalName": "Frangula",
            "rank": "GENUS",
            "taxonomicStatus": "ACCEPTED",
            "kingdom": "Plantae",
            "family": "Rhamnaceae",
            "synonym": False,
            "threatStatuses": [],
            "vernacularNames": [],
        },
        {
            # Missing scientific name -> skipped.
            "key": 999,
            "canonicalName": "Incomplete",
        },
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"count": 0, "results": []}


def _provider() -> GBIFSpeciesProvider:
    return GBIFSpeciesProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "gbif"
    assert p.tags == ["biodiversity", "nature", "science"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Panthera leo"
    assert r.url == "https://www.gbif.org/species/5219404"
    chain = "Animalia > Chordata > Mammalia > Carnivora > Felidae > Panthera"
    assert chain in r.snippet
    assert "SPECIES" in r.snippet
    assert "ACCEPTED" in r.snippet
    assert "Conservation: VULNERABLE" in r.snippet
    assert "Common: African lion, Lion" in r.snippet
    assert r.provider == "gbif"
    assert r.source == "gbif.org"
    assert r.rank == 1
    assert r.extra["scientific_name"] == "Panthera leo"
    assert r.extra["classification"] == (
        "Animalia > Chordata > Mammalia > Carnivora > Felidae > Panthera"
    )
    assert r.extra["threat_status"] == "VULNERABLE"
    assert r.extra["common_names"] == ["African lion", "Lion"]
    assert r.extra["num_occurrences"] == 12345


def test_parse_second_record() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    r = result.results[1]
    assert r.title == "Frangula"
    assert r.rank == 2
    assert r.extra["classification"] == "Plantae > Rhamnaceae"
    assert r.extra["threat_status"] == ""
    assert r.extra["common_names"] == []


def test_parse_skips_incomplete() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert all(r.title and r.url for r in result.results)


def test_parse_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1
    assert result.results[0].title == "Panthera leo"


def test_parse_empty_and_malformed() -> None:
    assert _provider()._parse(_EMPTY_RESPONSE).results == []
    assert _provider()._parse({"results": None}).results == []
    assert _provider()._parse({"results": "junk"}).results == []
    assert _provider()._parse({}).results == []
    assert _provider()._parse(None).results == []


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.gbif.org/v1/species/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("lion", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "gbif"
    request = respx_mock.calls.last.request
    assert request.url.params["q"] == "lion"
    assert request.url.params["limit"] == "5"


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.gbif.org/v1/species/search").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("zzz", SearchParams(num_results=5))
    assert result.results == []
