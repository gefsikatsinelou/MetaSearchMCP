"""Unit tests for the MyGene.info gene search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.mygene import MyGeneProvider

_SAMPLE_RESPONSE: dict[str, object] = {
    "took": 9,
    "total": 14549,
    "max_score": 145.1,
    "hits": [
        {
            "_id": "672",
            "_score": 145.1,
            "entrezgene": "672",
            "symbol": "BRCA1",
            "name": "BRCA1 DNA repair associated",
            "taxid": 9606,
            "type_of_gene": "protein-coding",
            "summary": "This gene encodes a nuclear phosphoprotein.",
            "genomic_pos": {
                "chr": "17",
                "start": 43044292,
                "end": 43170245,
                "strand": -1,
                "ensemblgene": "ENSG00000012048",
            },
            "alias": ["RNF53", "BRCC1", "FANCS", "PPP1R53", "PNCA4"],
            "uniprot": {"Swiss-Prot": "P38398"},
        },
        {
            # No symbol -> the full name is used; genomic_pos is a list.
            "_id": "12189",
            "name": "breast cancer 1, early onset",
            "taxid": 10090,
            "type_of_gene": "protein-coding",
            "genomic_pos": [
                {"chr": "11", "start": 101379577, "end": 101442781},
                {"chr": "scaffold", "start": 1, "end": 2},
            ],
            "alias": "Brca1",
            "uniprot": {"Swiss-Prot": ["P48754"]},
            "ensembl": {"gene": "ENSMUSG00000017146"},
        },
        {
            # Missing both symbol and name -> skipped entirely.
            "_id": "999",
            "taxid": 9606,
        },
        "junk",
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"took": 1, "total": 0, "hits": []}


def _provider() -> MyGeneProvider:
    return MyGeneProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "mygene"
    assert p.tags == ["academic", "web", "bio", "gene"]
    assert p.is_available() is True


def test_parse_basic_fields() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "BRCA1 (BRCA1 DNA repair associated)"
    assert r.url == "https://www.ncbi.nlm.nih.gov/gene/672"
    assert r.provider == "mygene"
    assert r.source == "mygene.info"
    assert r.rank == 1
    assert "Organism: human (9606)" in r.snippet
    assert "Type: protein-coding" in r.snippet
    assert "Chromosome: 17" in r.snippet
    assert "Aliases: RNF53, BRCC1, FANCS, PPP1R53" in r.snippet
    assert "phosphoprotein" in r.snippet
    assert r.extra["entrezgene"] == "672"
    assert r.extra["symbol"] == "BRCA1"
    assert r.extra["taxid"] == 9606
    assert r.extra["genomic_start"] == 43044292
    assert r.extra["genomic_end"] == 43170245
    assert r.extra["ensembl_gene"] == "ENSG00000012048"
    assert r.extra["uniprot"] == "P38398"
    assert r.extra["aliases"][0] == "RNF53"
    assert r.extra["total_results"] == 14549


def test_parse_handles_list_positions_and_string_aliases() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    second = result.results[1]
    # Only the full name is available -> used as the title.
    assert second.title == "breast cancer 1, early onset"
    assert second.rank == 2
    assert second.extra["organism"] == "mouse (10090)"
    assert second.extra["chromosome"] == "11"
    # ensemblgene missing on the first position -> falls back to ensembl.gene.
    assert second.extra["ensembl_gene"] == "ENSMUSG00000017146"
    assert second.extra["aliases"] == ["Brca1"]
    assert second.extra["uniprot"] == "P48754"


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
    assert result.results[0].title == "BRCA1 (BRCA1 DNA repair associated)"


def test_organism_label_fallbacks() -> None:
    assert MyGeneProvider._organism(9606) == "human (9606)"
    assert MyGeneProvider._organism(12345) == "taxid 12345"
    assert MyGeneProvider._organism(0) == ""


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get("https://mygene.info/v3/query").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    result = await _provider().search("BRCA1", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "mygene"
    assert len(respx_mock.calls) == 1
    request = respx_mock.calls[0].request
    assert request.url.params["q"] == "BRCA1"
    assert request.url.params["species"] == "all"
    assert request.url.params["size"] == "5"
    assert "symbol" in request.url.params["fields"]


@pytest.mark.asyncio
async def test_search_no_match(respx_mock) -> None:
    import respx

    respx_mock.get("https://mygene.info/v3/query").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    result = await _provider().search("zzzz", SearchParams(num_results=5))
    assert result.results == []
