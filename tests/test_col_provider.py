"""Unit tests for the Catalogue of Life (ChecklistBank) taxonomic search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.col import ColProvider

_SAMPLE_RESPONSE: dict[str, object] = {
    "offset": 0,
    "limit": 2,
    "total": 296,
    "result": [
        {
            "id": "4CGXP",
            "classification": [
                {
                    "id": "N",
                    "name": "Animalia",
                    "rank": "kingdom",
                    "status": "accepted",
                },
                {
                    "id": "CH2",
                    "name": "Chordata",
                    "rank": "phylum",
                    "status": "accepted",
                },
                {
                    "id": "6224G",
                    "name": "Mammalia",
                    "rank": "class",
                    "status": "accepted",
                },
                {
                    "id": "FH",
                    "name": "Carnivora",
                    "rank": "order",
                    "status": "accepted",
                },
                {"id": "3p", "name": "Felidae", "rank": "family", "status": "accepted"},
                {
                    "id": "4CGXQ",
                    "name": "Panthera",
                    "rank": "genus",
                    "status": "accepted",
                },
            ],
            "group": "chordates",
            "usage": {
                "id": "4CGXP",
                "status": "accepted",
                "label": "Panthera leo (Linnaeus, 1758)",
                "link": "https://www.itis.gov/servlet/SingleRpt?search_value=183803",
                "name": {
                    "scientificName": "Panthera leo",
                    "authorship": "(Linnaeus, 1758)",
                    "rank": "species",
                    "genus": "Panthera",
                    "specificEpithet": "leo",
                    "code": "zoological",
                    "nomStatus": "acceptable",
                },
            },
            "vernacularNames": [
                {"name": "Lion", "language": "eng"},
                {"name": "Löwe", "language": "deu"},
            ],
        },
        {
            "id": "XSPARSE",
            "usage": {
                "id": "XSPARSE",
                "status": "synonym",
                "name": {"scientificName": "Sparse species", "rank": "species"},
            },
        },
        # Non-dict payload -> skipped.
        "junk",
        None,
        # usage without a name -> skipped.
        {"id": "Y", "usage": {}},
        # No usage at all -> skipped.
        {"id": "Z"},
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"offset": 0, "limit": 0, "total": 0, "result": []}


def _provider() -> ColProvider:
    return ColProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "col"
    assert p.tags == ["biodiversity", "nature", "science"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert [r.title for r in result.results] == [
        "Panthera leo (Linnaeus, 1758)",
        "Sparse species",
    ]
    r = result.results[0]
    assert r.url == "https://www.catalogueoflife.org/data/taxon/4CGXP"
    assert r.provider == "col"
    assert r.source == "catalogueoflife.org"
    assert r.rank == 1
    assert r.published_date is None
    assert "species" in r.snippet
    assert "accepted" in r.snippet
    assert "group: chordates" in r.snippet
    assert (
        "Animalia > Chordata > Mammalia > Carnivora > Felidae > Panthera" in r.snippet
    )
    assert "common: Lion, Löwe" in r.snippet
    assert r.extra["scientific_name"] == "Panthera leo"
    assert r.extra["authorship"] == "(Linnaeus, 1758)"
    assert r.extra["rank"] == "species"
    assert r.extra["status"] == "accepted"
    assert r.extra["genus"] == "Panthera"
    assert r.extra["specific_epithet"] == "leo"
    assert r.extra["code"] == "zoological"
    assert r.extra["nom_status"] == "acceptable"
    assert r.extra["lineage"] == [
        "Animalia",
        "Chordata",
        "Mammalia",
        "Carnivora",
        "Felidae",
        "Panthera",
    ]
    assert r.extra["common_names"] == ["Lion", "Löwe"]
    assert r.extra["source_link"].startswith("https://www.itis.gov/")


def test_parse_sparse_record() -> None:
    r = _provider()._parse(_SAMPLE_RESPONSE).results[1]
    assert r.title == "Sparse species"
    assert r.url == "https://www.catalogueoflife.org/data/taxon/XSPARSE"
    assert r.extra["status"] == "synonym"
    assert r.extra["lineage"] == []
    assert r.extra["common_names"] == []
    assert r.rank == 2


def test_parse_drops_malformed_entries() -> None:
    titles = {r.title for r in _provider()._parse(_SAMPLE_RESPONSE).results}
    assert "junk" not in titles
    assert len(_provider()._parse(_SAMPLE_RESPONSE).results) == 2


def test_parse_empty_and_junk() -> None:
    p = _provider()
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []
    assert p._parse({"result": "junk"}).results == []  # type: ignore[dict-item]
    assert p._parse([1, 2, 3]).results == []  # type: ignore[arg-type]
    assert p._parse(None).results == []  # type: ignore[arg-type]


def test_parse_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1
    assert result.results[0].extra["id"] == "4CGXP"


def test_parse_snippet_capped_at_shared_limit() -> None:
    from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH

    long_common = "x" * (MAX_SNIPPET_LENGTH + 200)
    result = _provider()._parse(
        {
            "result": [
                {
                    "id": "LONG",
                    "usage": {"name": {"scientificName": "T", "rank": "species"}},
                    "vernacularNames": [{"name": long_common, "language": "eng"}],
                },
            ],
        },
    )
    assert len(result.results[0].snippet) == MAX_SNIPPET_LENGTH


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_query_params(respx_mock) -> None:
    import respx

    respx_mock.get(
        "https://api.checklistbank.org/dataset/3LR/nameusage/search",
    ).mock(return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE))

    p = _provider()
    result = await p.search("panthera leo", SearchParams(num_results=5))

    assert len(result.results) == 2
    request = respx_mock.calls.last.request
    assert request.url.params["q"] == "panthera leo"
    assert request.url.params["limit"] == "5"


@pytest.mark.asyncio
async def test_search_empty_query_short_circuits(respx_mock) -> None:
    import respx

    route = respx_mock.get(
        "https://api.checklistbank.org/dataset/3LR/nameusage/search",
    ).mock(return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE))

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get(
        "https://api.checklistbank.org/dataset/3LR/nameusage/search",
    ).mock(return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE))

    result = await _provider().search("no-such-taxon-xyz", SearchParams(num_results=5))
    assert result.results == []
