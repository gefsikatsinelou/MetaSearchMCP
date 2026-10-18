"""Unit tests for the EMBL-EBI PRIDE proteomics dataset search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.pride import PrideProvider

_SAMPLE_RESPONSE: list[object] = [
    {
        "accession": "PXD039769",
        "title": "CDK16 and CDK18 inhibition in hepatocellular carcinoma",
        "projectDescription": "Proteomics of CDK16/18 inhibition in HCC models.",
        "submissionDate": "2023-02-01",
        "publicationDate": "2026-10-15",
        "submissionType": "PARTIAL",
        "organisms": ["Mus musculus (mouse)", "Homo sapiens (human)"],
        "instruments": ["Q Exactive HF"],
        "keywords": ["Cdk16", "Cdk18"],
        "labPIs": ["Javier Munoz Peralta"],
        "affiliations": ["CNIO"],
        "experimentTypes": ["Shotgun proteomics"],
        "quantificationMethods": ["Label-free"],
        "diseases": ["Hepatocellular carcinoma"],
        "downloadCount": 42,
        "doi": "10.6019/PXD039769",
    },
    {
        "accession": "PXD000001",
        "title": "Sparse record",
        "submissionDate": "2011-01-01",
    },
    # Non-dict payload -> skipped.
    "junk",
    None,
    # Missing both accession and title -> skipped.
    {"projectDescription": "no title here"},
]

_EMPTY_RESPONSE: list[object] = []


def _provider() -> PrideProvider:
    return PrideProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "pride"
    assert p.tags == ["bio", "academic", "science", "data", "datasets"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert [r.title for r in result.results] == [
        "CDK16 and CDK18 inhibition in hepatocellular carcinoma",
        "Sparse record",
    ]
    r = result.results[0]
    assert r.url == "https://www.ebi.ac.uk/pride/archive/projects/PXD039769"
    assert r.provider == "pride"
    assert r.source == "ebi.ac.uk"
    assert r.rank == 1
    assert r.published_date == "2026-10-15"
    assert "Proteomics of CDK16/18" in r.snippet
    assert "organisms: Mus musculus (mouse), Homo sapiens (human)" in r.snippet
    assert "instruments: Q Exactive HF" in r.snippet
    assert "experiment types: Shotgun proteomics" in r.snippet
    assert "keywords: Cdk16, Cdk18" in r.snippet
    assert "PI: Javier Munoz Peralta" in r.snippet
    assert r.extra["accession"] == "PXD039769"
    assert r.extra["organisms"] == ["Mus musculus (mouse)", "Homo sapiens (human)"]
    assert r.extra["lab_pis"] == ["Javier Munoz Peralta"]
    assert r.extra["affiliations"] == ["CNIO"]
    assert r.extra["submission_type"] == "PARTIAL"
    assert r.extra["download_count"] == 42
    assert r.extra["doi"] == "10.6019/PXD039769"


def test_parse_sparse_record() -> None:
    r = _provider()._parse(_SAMPLE_RESPONSE).results[1]
    assert r.title == "Sparse record"
    assert r.url == "https://www.ebi.ac.uk/pride/archive/projects/PXD000001"
    assert r.published_date == "2011-01-01"
    # Only the title is present, so the snippet is empty.
    assert r.snippet == ""
    assert r.extra["organisms"] == []
    assert r.extra["download_count"] is None
    assert r.rank == 2


def test_parse_drops_malformed_entries() -> None:
    titles = {r.title for r in _provider()._parse(_SAMPLE_RESPONSE).results}
    assert "junk" not in titles
    assert "no title here" not in titles


def test_parse_empty_and_junk() -> None:
    p = _provider()
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []  # type: ignore[arg-type]
    assert p._parse("junk").results == []  # type: ignore[arg-type]
    assert p._parse(None).results == []  # type: ignore[arg-type]


def test_parse_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1
    assert result.results[0].extra["accession"] == "PXD039769"


def test_parse_snippet_capped_at_shared_limit() -> None:
    from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH

    long_description = "x" * (MAX_SNIPPET_LENGTH + 200)
    result = _provider()._parse(
        [{"accession": "PXD1", "title": "T", "projectDescription": long_description}],
    )
    assert len(result.results[0].snippet) == MAX_SNIPPET_LENGTH


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_keyword_param(respx_mock) -> None:
    import respx

    respx_mock.get(
        "https://www.ebi.ac.uk/pride/ws/archive/v2/search/projects",
    ).mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("proteomics", SearchParams(num_results=5))

    assert len(result.results) == 2
    request = respx_mock.calls.last.request
    assert request.url.params["keyword"] == "proteomics"
    assert request.url.params["pageSize"] == "5"


@pytest.mark.asyncio
async def test_search_empty_query_short_circuits(respx_mock) -> None:
    import respx

    route = respx_mock.get(
        "https://www.ebi.ac.uk/pride/ws/archive/v2/search/projects",
    ).mock(return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE))

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get(
        "https://www.ebi.ac.uk/pride/ws/archive/v2/search/projects",
    ).mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    result = await _provider().search(
        "no-such-dataset-xyz",
        SearchParams(num_results=5),
    )
    assert result.results == []
