"""Unit tests for the keyless NCBI Gene E-utilities search provider.

Covers the two-step esearch/esummary flow, parsing (including records
with missing fields), the pure helper functions, result limits, the blank
query short-circuit and API error handling.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.ncbi_gene import NcbiGeneProvider

_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

_BRCA2: dict[str, Any] = {
    "uid": "675",
    "name": "BRCA2",
    "description": "BRCA2 DNA repair associated",
    "chromosome": "13",
    "maplocation": "13q13.1",
    "otheraliases": "FANCD1, FAD, BRCC2",
    "organism": {
        "scientificname": "Homo sapiens",
        "commonname": "human",
        "taxid": 9606,
    },
    "summary": (
        "Involved in maintenance of genome stability and double-strand break repair."
    ),
}


def _esearch_payload(id_list: list[str]) -> dict[str, Any]:
    """Wrap *id_list* in the ESearch response shape."""
    return {"esearchresult": {"idlist": id_list, "count": str(len(id_list))}}


def _esummary_payload(*items: dict[str, Any]) -> dict[str, Any]:
    """Wrap *items* in the ESummary response shape keyed by uid."""
    result: dict[str, Any] = {str(item["uid"]): item for item in items}
    result["uids"] = [str(item["uid"]) for item in items]
    return {"result": result}


def test_ncbi_gene_name_tags_and_availability() -> None:
    p = NcbiGeneProvider()
    assert p.name == "ncbi_gene"
    assert p.tags == ["bio", "medical", "academic"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_ncbi_gene_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "ncbi_gene" in registry
    assert registry["ncbi_gene"].tags == ["bio", "medical", "academic"]


def test_ncbi_gene_parse_single_hit() -> None:
    p = NcbiGeneProvider()
    result = p._parse(_esummary_payload(_BRCA2), ["675"], limit=5)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "BRCA2 (BRCA2 DNA repair associated)"
    assert r.url == "https://www.ncbi.nlm.nih.gov/gene/675"
    assert r.source == "ncbi.nlm.nih.gov"
    assert r.provider == "ncbi_gene"
    assert r.rank == 1
    assert r.snippet == (
        "Homo sapiens | Chromosome: 13 | Location: 13q13.1 | "
        "Aliases: FANCD1, FAD, BRCC2 | "
        "Involved in maintenance of genome stability and double-strand break repair."
    )
    assert r.extra["gene_id"] == "675"
    assert r.extra["symbol"] == "BRCA2"
    assert r.extra["organism"] == "Homo sapiens"
    assert r.extra["aliases"] == ["FANCD1", "FAD", "BRCC2"]


def test_ncbi_gene_parse_preserves_requested_order_and_ranks() -> None:
    p = NcbiGeneProvider()
    other = {
        "uid": "672",
        "name": "BRCA1",
        "description": "BRCA1 DNA repair associated",
    }
    # Requested order differs from the summary's insertion order.
    result = p._parse(_esummary_payload(other, _BRCA2), ["675", "672"])

    assert [r.extra["symbol"] for r in result.results] == ["BRCA2", "BRCA1"]
    assert [r.rank for r in result.results] == [1, 2]


def test_ncbi_gene_parse_skips_missing_and_unusable_records() -> None:
    p = NcbiGeneProvider()
    payload = _esummary_payload(
        {"uid": "1", "name": "", "description": ""},
        {"uid": "2", "name": "TP53", "description": ""},
    )

    results = p._parse(payload, ["0", "1", "2"], limit=10).results
    # "0" is absent from the summary and "1" has nothing usable.
    assert [r.title for r in results] == ["TP53"]
    assert results[0].url == "https://www.ncbi.nlm.nih.gov/gene/2"
    assert results[0].rank == 1


def test_ncbi_gene_parse_respects_limit() -> None:
    p = NcbiGeneProvider()
    items = [
        {"uid": str(n), "name": f"GENE{n}", "description": "d"} for n in range(1, 6)
    ]
    ids = [str(n) for n in range(1, 6)]

    assert len(p._parse(_esummary_payload(*items), ids, limit=2).results) == 2
    assert len(p._parse(_esummary_payload(*items), ids).results) == 5


def test_ncbi_gene_parse_empty_and_malformed() -> None:
    p = NcbiGeneProvider()
    assert p._parse({}, ["1"]).results == []
    assert p._parse([], ["1"]).results == []
    assert p._parse("nope", ["1"]).results == []
    assert p._parse(None, ["1"]).results == []
    assert p._parse({"result": "nope"}, ["1"]).results == []
    assert p._parse(_esummary_payload(_BRCA2), []).results == []


def test_ncbi_gene_id_list_extraction() -> None:
    p = NcbiGeneProvider()
    assert p._id_list(_esearch_payload(["675", "672"])) == ["675", "672"]
    assert p._id_list({"esearchresult": {"idlist": [675, 672]}}) == ["675", "672"]
    assert p._id_list({}) == []
    assert p._id_list("nope") == []
    assert p._id_list({"esearchresult": {"idlist": "nope"}}) == []


def test_ncbi_gene_helpers() -> None:
    from metasearchmcp.providers.ncbi_gene import (
        _aliases,
        _organism,
        _text,
    )

    assert _text("  a\n  b  ") == "a b"
    assert _text(675) == "675"
    assert _text(True) == ""
    assert _text(None) == ""
    assert _aliases("FANCD1, FAD , BRCC2") == ["FANCD1", "FAD", "BRCC2"]
    assert _aliases(None) == []
    assert _organism({"scientificname": "Homo sapiens"}) == "Homo sapiens"
    assert _organism({"commonname": "human"}) == "human"
    assert _organism("nope") == ""


async def test_ncbi_gene_search_hits_api_and_parses(respx_mock) -> None:
    esearch = respx_mock.get(_ESEARCH).mock(
        return_value=respx.MockResponse(200, json=_esearch_payload(["675"])),
    )
    respx_mock.get(_ESUMMARY).mock(
        return_value=respx.MockResponse(200, json=_esummary_payload(_BRCA2)),
    )

    result = await NcbiGeneProvider().search("BRCA2", SearchParams(num_results=5))

    assert esearch.called
    request = esearch.calls[0].request
    assert request.url.params["db"] == "gene"
    assert request.url.params["term"] == "BRCA2"
    assert request.url.params["retmax"] == "5"
    assert request.url.params["sort"] == "relevance"
    assert [r.extra["symbol"] for r in result.results] == ["BRCA2"]


async def test_ncbi_gene_search_skips_esummary_when_no_ids(respx_mock) -> None:
    respx_mock.get(_ESEARCH).mock(
        return_value=respx.MockResponse(200, json=_esearch_payload([])),
    )
    summary_route = respx_mock.get(_ESUMMARY)

    result = await NcbiGeneProvider().search("zzzqqq", SearchParams())

    assert result.results == []
    assert not summary_route.called


async def test_ncbi_gene_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_ESEARCH)

    result = await NcbiGeneProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_ncbi_gene_search_respects_result_limits(respx_mock) -> None:
    ids = [str(n) for n in range(1, 41)]
    items = [{"uid": n, "name": f"GENE{n}", "description": "d"} for n in range(1, 41)]
    respx_mock.get(_ESEARCH).mock(
        return_value=respx.MockResponse(200, json=_esearch_payload(ids)),
    )
    respx_mock.get(_ESUMMARY).mock(
        return_value=respx.MockResponse(200, json=_esummary_payload(*items)),
    )

    provider = NcbiGeneProvider()
    provider._max_results = 1000
    result = await provider.search("gene", SearchParams(num_results=30))
    assert len(result.results) == 30

    provider._max_results = 1
    result = await provider.search("gene", SearchParams(num_results=30))
    assert len(result.results) == 1


async def test_ncbi_gene_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_ESEARCH).mock(return_value=respx.MockResponse(500))

    with pytest.raises(httpx.HTTPStatusError):
        await NcbiGeneProvider().search("BRCA2", SearchParams())
