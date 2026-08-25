"""Unit tests for the UniProt protein knowledgebase search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.uniprot import UniProtProvider

_RESPONSE = {
    "results": [
        {
            "primaryAccession": "P01308",
            "uniProtkbId": "INS_HUMAN",
            "proteinDescription": {
                "recommendedName": {"fullName": {"value": "Insulin"}},
            },
            "organism": {"scientificName": "Homo sapiens", "taxonId": 9606},
            "genes": [{"geneName": {"value": "INS"}}],
            "entryType": "UniProtKB reviewed (Swiss-Prot)",
            "keywords": [
                {"name": "3D-structure"},
                {"name": "Diabetes mellitus"},
            ],
            "comments": [
                {
                    "commentType": "FUNCTION",
                    "texts": [
                        {"value": "Insulin reduces blood glucose concentration."},
                    ],
                },
            ],
            "sequence": {"length": 110},
        },
        {
            "primaryAccession": "P0DP23",
            "uniProtkbId": "CALM1_HUMAN",
            "proteinDescription": {
                "recommendedName": {"fullName": {"value": "Calmodulin-1"}},
            },
            "organism": {"scientificName": "Homo sapiens", "taxonId": 9606},
            "entryType": "UniProtKB reviewed (Swiss-Prot)",
            "sequence": {"length": 148},
        },
        {
            # Missing accession -> skipped.
            "uniProtkbId": "NO_ACCESSION",
        },
    ],
}


def _provider() -> UniProtProvider:
    return UniProtProvider()


def test_parse_basic() -> None:
    result = _provider()._parse(_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Insulin"
    assert r.url == "https://www.uniprot.org/uniprotkb/P01308/entry"
    assert r.provider == "uniprot"
    assert r.source == "uniprot.org"
    assert r.rank == 1
    assert "Organism: Homo sapiens" in r.snippet
    assert "Gene: INS" in r.snippet
    assert "Swiss-Prot" in r.snippet
    assert r.extra["accession"] == "P01308"
    assert r.extra["entry_name"] == "INS_HUMAN"
    assert r.extra["gene"] == ["INS"]
    assert r.extra["organism"] == "Homo sapiens"
    assert r.extra["taxon_id"] == 9606
    assert r.extra["entry_type"] == "reviewed (Swiss-Prot)"
    assert r.extra["sequence_length"] == 110
    assert "Diabetes mellitus" in r.extra["keywords"]


def test_parse_snippet_function_truncation() -> None:
    long_text = "x" * 500
    data = {
        "results": [
            {
                "primaryAccession": "P12345",
                "proteinDescription": {
                    "recommendedName": {"fullName": {"value": "Long protein"}},
                },
                "comments": [
                    {"commentType": "FUNCTION", "texts": [{"value": long_text}]},
                ],
                "sequence": {"length": 1},
            },
        ],
    }
    result = _provider()._parse(data)
    assert len(result.results) == 1
    snippet = result.results[0].snippet
    assert len(snippet) == 300


def test_parse_protein_name_fallbacks() -> None:
    # No recommended name -> falls back to entry name.
    data = {
        "results": [
            {
                "primaryAccession": "P99999",
                "uniProtkbId": "TR_ENTRY",
                "proteinDescription": {"submissionNames": None},
                "sequence": {"length": 50},
            },
        ],
    }
    result = _provider()._parse(data)
    assert result.results[0].title == "TR_ENTRY"

    # submissionNames supplies the name when recommendedName is missing.
    data["results"][0]["proteinDescription"] = {
        "submissionNames": [{"fullName": {"value": "Putative protein"}}],
    }
    result = _provider()._parse(data)
    assert result.results[0].title == "Putative protein"


def test_parse_empty_and_malformed() -> None:
    assert _provider()._parse({}).results == []
    assert _provider()._parse({"results": ["not-a-dict", None, 42]}).results == []


def test_parse_limit() -> None:
    result = _provider()._parse(_RESPONSE, max_results=1)
    assert len(result.results) == 1
    assert result.results[0].extra["accession"] == "P01308"


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_endpoint(respx_mock) -> None:
    import respx

    respx_mock.get(
        "https://rest.uniprot.org/uniprotkb/search",
        params={"query": "insulin", "format": "json", "size": 5},
    ).mock(
        return_value=respx.MockResponse(200, json=_RESPONSE),
    )

    p = _provider()
    result = await p.search("insulin", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "uniprot"
    assert result.results[0].url.startswith("https://www.uniprot.org/uniprotkb/")
