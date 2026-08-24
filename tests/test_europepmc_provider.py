"""Unit tests for the Europe PMC scholarly literature search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.europepmc import EuropePmcProvider

_RESPONSE = {
    "hitCount": 2,
    "resultList": {
        "result": [
            {
                "id": "42525473",
                "source": "MED",
                "pmid": "42525473",
                "doi": "10.1002/vms3.71122",
                "title": (
                    "Treatment of Potential Postpartum Eclampsia in a Python "
                    "Using Traditional Chinese Veterinary Medicine"
                ),
                "authorString": "Yang S, Liu Y, Mi J, Chang LJ, Ma WR.",
                "journalTitle": "Vet Med Sci",
                "pubYear": "2026",
                "isOpenAccess": "N",
                "firstPublicationDate": "2026-09-01",
            },
            {
                "id": "42525474",
                "source": "PPR",
                "pmid": "",
                "doi": "10.1101/2026.03.01.999999",
                "title": "A preprint about metacognitive search agents",
                "authorString": "Doe J, Smith A",
                "journalTitle": "",
                "pubYear": "2026",
                "isOpenAccess": "Y",
                "firstPublicationDate": "",
            },
            {
                # Missing title and identifiers -> skipped by the parser.
                "id": "42525475",
                "source": "MED",
                "title": "",
            },
        ],
    },
}


def _provider() -> EuropePmcProvider:
    return EuropePmcProvider()


def test_parse_basic() -> None:
    result = _provider()._parse(_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title.startswith("Treatment of Potential Postpartum Eclampsia")
    assert r.url == "https://europepmc.org/article/MED/42525473"
    assert r.provider == "europepmc"
    assert r.source == "europepmc.org"
    assert r.rank == 1
    assert r.published_date == "2026"
    assert "Vet Med Sci" in r.snippet
    assert "Yang S" in r.snippet
    assert r.extra["pmid"] == "42525473"
    assert r.extra["doi"] == "10.1002/vms3.71122"
    assert r.extra["open_access"] is False
    assert r.extra["source_db"] == "MED"


def test_parse_preprint_with_doi_fallback() -> None:
    result = _provider()._parse(_RESPONSE)
    r = result.results[1]

    assert r.url == "https://doi.org/10.1101/2026.03.01.999999"
    assert r.extra["pmid"] == ""
    assert r.extra["open_access"] is True
    assert r.extra["source_db"] == "PPR"
    assert "Open Access" in r.snippet
    assert r.extra["authors"] == ["Doe J", "Smith A"]


def test_parse_limit() -> None:
    result = _provider()._parse(_RESPONSE, max_results=1)
    assert len(result.results) == 1


def test_parse_empty() -> None:
    result = _provider()._parse({})
    assert result.results == []


def test_parse_malformed_items() -> None:
    data = {"resultList": {"result": ["not-a-dict", None, 42]}}
    result = _provider()._parse(data)
    assert result.results == []


def test_authors_splits_and_strips() -> None:
    assert EuropePmcProvider._authors({"authorString": " Yang S , Liu Y "}) == [
        "Yang S",
        "Liu Y",
    ]
    assert EuropePmcProvider._authors({"authorString": ""}) == []


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_endpoint(respx_mock) -> None:
    import respx

    respx_mock.get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={
            "query": "python",
            "format": "json",
            "pageSize": 5,
            "resultType": "lite",
        },
    ).mock(
        return_value=respx.MockResponse(200, json=_RESPONSE),
    )

    p = _provider()
    result = await p.search("python", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "europepmc"
    assert result.results[0].url.startswith("https://europepmc.org/article/MED/")
