"""Unit tests for the MyVariant.info genetic variant search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.myvariant import MyVariantProvider

_SAMPLE_RESPONSE: dict[str, object] = {
    "took": 5,
    "total": 3,
    "max_score": 17.14,
    "hits": [
        {
            "_id": "chr7:g.140453136A>G",
            "_score": 17.14,
            "dbnsfp": {
                "genename": ["BRAF", "BRAF"],
                "hgvsp": ["p.Val600Ala", "p.V600A"],
            },
            "dbsnp": {"rsid": "rs113488022"},
            "cadd": {"phred": 21.2},
        },
        {
            # No dbNSFP -> falls back to ClinVar gene + SnpEff protein change.
            "_id": "chr7:g.117199602C>T",
            "clinvar": {
                "gene": {"symbol": "CFTR"},
                "rcv": [
                    {
                        "clinical_significance": "Pathogenic",
                        "conditions": {"name": "Cystic fibrosis (CF)"},
                    },
                    {
                        "clinical_significance": "Pathogenic",
                        "conditions": [
                            {"name": "Cystic fibrosis (CF)"},
                            {"name": "CFTR-related disorder (CFTR-RD)"},
                        ],
                    },
                ],
            },
            "snpeff": {"ann": {"hgvs_p": "p.Phe508del", "gene_name": "CFTR"}},
        },
        {
            # Only a variant id -> the id itself is used as the title.
            "_id": "chr1:g.100A>T",
        },
        "junk",
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"took": 1, "total": 0, "hits": []}


def _provider() -> MyVariantProvider:
    return MyVariantProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "myvariant"
    assert p.tags == ["academic", "web", "bio", "genomics"]
    assert p.is_available() is True


def test_parse_basic_fields() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 3
    r = result.results[0]
    assert r.title == "BRAF p.Val600Ala"
    assert r.url == "https://www.ncbi.nlm.nih.gov/snp/rs113488022"
    assert r.provider == "myvariant"
    assert r.source == "myvariant.info"
    assert r.rank == 1
    assert "Gene: BRAF" in r.snippet
    assert "Protein change: p.Val600Ala" in r.snippet
    assert "rsID: rs113488022" in r.snippet
    assert "CADD phred: 21.2" in r.snippet
    assert r.extra["variant_id"] == "chr7:g.140453136A>G"
    assert r.extra["gene"] == "BRAF"
    assert r.extra["genes"] == ["BRAF", "BRAF"]
    assert r.extra["hgvsp"] == "p.Val600Ala"
    assert r.extra["cadd_phred"] == 21.2
    assert r.extra["total_results"] == 3


def test_parse_clinvar_fallbacks_and_dedup() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    second = result.results[1]
    assert second.title == "CFTR p.Phe508del"
    assert second.rank == 2
    assert "Clinical significance: Pathogenic" in second.snippet
    assert "Conditions: Cystic fibrosis (CF), CFTR-related disorder (CFTR-RD)" in (
        second.snippet
    )
    # Duplicate "Pathogenic" and "Cystic fibrosis (CF)" are collapsed.
    assert second.extra["clinical_significance"] == ["Pathogenic"]
    assert second.extra["conditions"] == [
        "Cystic fibrosis (CF)",
        "CFTR-related disorder (CFTR-RD)",
    ]
    assert second.extra["variant_id"] == "chr7:g.117199602C>T"
    assert second.url == "https://myvariant.info/v1/variant/chr7:g.117199602C>T"


def test_parse_id_only_hit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    third = result.results[2]
    assert third.title == "chr1:g.100A>T"
    assert third.url == "https://myvariant.info/v1/variant/chr1:g.100A>T"
    assert third.rank == 3
    assert third.extra["gene"] == ""


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse({}).results == []
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({"hits": "nope"}).results == []
    assert p._parse({"hits": [42, None]}).results == []
    assert p._parse("junk").results == []


def test_parse_respects_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1
    assert result.results[0].title == "BRAF p.Val600Ala"


def test_condition_name_variants() -> None:
    p = _provider()
    assert p._condition_names("Single condition") == ["Single condition"]
    assert p._condition_names([{"name": "A"}, {"name": "B"}]) == ["A", "B"]
    assert p._condition_names(["A", "A"]) == ["A"]
    assert p._condition_names(None) == []


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get("https://myvariant.info/v1/query").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    result = await _provider().search("rs113488022", SearchParams(num_results=5))

    assert len(result.results) == 3
    assert result.results[0].provider == "myvariant"
    assert len(respx_mock.calls) == 1
    request = respx_mock.calls[0].request
    assert request.url.params["q"] == "rs113488022"
    assert request.url.params["size"] == "5"
    assert "dbnsfp.genename" in request.url.params["fields"]


@pytest.mark.asyncio
async def test_search_no_match(respx_mock) -> None:
    import respx

    respx_mock.get("https://myvariant.info/v1/query").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    result = await _provider().search("zzzz", SearchParams(num_results=5))
    assert result.results == []
