"""Unit tests for the ClinVar clinically reported genetic variants provider."""

from __future__ import annotations

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.clinvar import ClinVarProvider

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
_VARIATION_PREFIX = "https://www.ncbi.nlm.nih.gov/clinvar/variation/"


def _esearch_payload(id_list: list[str]) -> dict:
    """An esearch response body resolving to *id_list*."""
    return {"esearchresult": {"idlist": id_list, "count": str(len(id_list))}}


def _record(uid: str = "4975019", **overrides) -> dict:
    """A ClinVar esummary document block with sensible defaults."""
    record = {
        "uid": uid,
        "obj_type": "single nucleotide variant",
        "accession": "VCV004975019",
        "title": "NM_000465.4(BARD1):c.188T>G (p.Leu63Ter)",
        "gene_sort": "BARD1",
        "genes": [{"symbol": "BARD1", "geneid": "580"}],
        "protein_change": "L63*",
        "molecular_consequence_list": ["nonsense", "intron variant"],
        "variation_set": [
            {
                "variation_name": "NM_000465.4(BARD1):c.188T>G (p.Leu63Ter)",
                "cdna_change": "c.188T>G",
                "variant_type": "single nucleotide variant",
            },
        ],
        "germline_classification": {
            "description": "Likely pathogenic",
            "review_status": "criteria provided, single submitter",
            "last_evaluated": "2026/09/12 00:00",
            "trait_set": [
                {"trait_name": "Hereditary cancer-predisposing syndrome"},
            ],
        },
    }
    record.update(overrides)
    return record


def _esummary_payload(*records: dict) -> dict:
    """An esummary response body containing the given document blocks."""
    result: dict = {"uids": [r["uid"] for r in records]}
    for record in records:
        result[record["uid"]] = record
    return {"result": result}


def _provider() -> ClinVarProvider:
    """Return a fresh provider instance for each test."""
    return ClinVarProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "clinvar"
    assert p.tags == ["academic", "bio", "medical", "science"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "clinvar" in registry
    assert registry["clinvar"].tags == ["academic", "bio", "medical", "science"]


def test_parse_builds_structured_result() -> None:
    p = _provider()
    result = p._parse(_esummary_payload(_record()), ["4975019"])

    assert len(result.results) == 1
    hit = result.results[0]
    assert hit.title == "NM_000465.4(BARD1):c.188T>G (p.Leu63Ter)"
    assert hit.url == f"{_VARIATION_PREFIX}4975019/"
    assert hit.source == "ncbi.nlm.nih.gov"
    assert hit.provider == "clinvar"
    assert hit.rank == 1
    assert hit.published_date == "2026-09-12"
    assert hit.snippet == (
        "single nucleotide variant | BARD1 | Likely pathogenic | p.L63* | "
        "Hereditary cancer-predisposing syndrome"
    )
    assert hit.extra == {
        "uid": "4975019",
        "accession": "VCV004975019",
        "obj_type": "single nucleotide variant",
        "gene": "BARD1",
        "classification": "Likely pathogenic",
        "review_status": "criteria provided, single submitter",
        "traits": ["Hereditary cancer-predisposing syndrome"],
        "variant_type": "single nucleotide variant",
        "cdna_change": "c.188T>G",
        "protein_change": "L63*",
        "molecular_consequence": ["nonsense", "intron variant"],
    }


def test_parse_ranks_sequentially_across_records() -> None:
    p = _provider()
    second = _record(uid="4970", title="Second variant")
    result = p._parse(_esummary_payload(_record(), second), ["4975019", "4970"])

    assert [r.rank for r in result.results] == [1, 2]
    assert [r.title for r in result.results] == [
        "NM_000465.4(BARD1):c.188T>G (p.Leu63Ter)",
        "Second variant",
    ]


def test_parse_skips_missing_or_empty_items() -> None:
    p = _provider()
    # 999 is requested but absent from the esummary map, 42 is an empty block.
    payload = _esummary_payload(_record())
    payload["result"]["42"] = {}

    result = p._parse(payload, ["4975019", "999", "42"])

    assert [r.extra["uid"] for r in result.results] == ["4975019"]
    assert result.results[0].rank == 1


def test_parse_falls_back_to_somatic_classification() -> None:
    p = _provider()
    record = _record(
        germline_classification={},
        clinical_impact_classification={
            "description": "Tier I - Strong",
            "review_status": "reviewed by expert panel",
            "last_evaluated": "2025/01/02 00:00",
            "trait_set": [{"trait_name": "Lung adenocarcinoma"}],
        },
    )
    result = p._parse(_esummary_payload(record), [record["uid"]])

    hit = result.results[0]
    assert hit.extra["classification"] == "Tier I - Strong"
    assert hit.extra["traits"] == ["Lung adenocarcinoma"]
    assert hit.published_date == "2025-01-02"


def test_parse_deduplicates_traits() -> None:
    p = _provider()
    record = _record(
        germline_classification={
            "description": "Pathogenic",
            "trait_set": [
                {"trait_name": "Breast cancer"},
                {"trait_name": "Breast cancer"},
                {"trait_name": "Ovarian cancer"},
            ],
        },
    )
    result = p._parse(_esummary_payload(record), [record["uid"]])

    assert result.results[0].extra["traits"] == ["Breast cancer", "Ovarian cancer"]


def test_parse_gene_fallback_to_genes_list() -> None:
    p = _provider()
    record = _record(gene_sort="", genes=[{"symbol": "TP53"}])
    result = p._parse(_esummary_payload(record), [record["uid"]])

    assert result.results[0].extra["gene"] == "TP53"


def test_parse_trims_multi_transcript_protein_change() -> None:
    p = _provider()
    record = _record(protein_change="I1808fs, I1855fs, I1876fs, I751fs")
    result = p._parse(_esummary_payload(record), [record["uid"]])

    hit = result.results[0]
    assert hit.extra["protein_change"] == "I1808fs"
    assert "p.I1808fs" in hit.snippet
    assert "I1855fs" not in hit.snippet


def test_parse_title_falls_back_to_accession() -> None:
    p = _provider()
    record = _record(title="", accession="VCV000012345", variation_set=[])
    result = p._parse(_esummary_payload(record), [record["uid"]])

    assert result.results[0].title == "VCV000012345"


def test_parse_empty_payloads() -> None:
    p = _provider()
    assert p._parse({}, []).results == []
    assert p._parse({"result": {}}, ["1"]).results == []
    assert p._parse({"result": "nonsense"}, ["1"]).results == []


def test_normalize_date() -> None:
    from metasearchmcp.providers.clinvar import _normalize_date

    assert _normalize_date("2026/09/12 00:00") == "2026-09-12"
    assert _normalize_date("2026/09/12") == "2026-09-12"
    assert _normalize_date("") is None
    assert _normalize_date(None) is None


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    respx_mock.get(_ESEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=_esearch_payload(["4975019"])),
    )
    respx_mock.get(_ESUMMARY_URL).mock(
        return_value=respx.MockResponse(200, json=_esummary_payload(_record())),
    )

    result = await _provider().search("BARD1", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "clinvar"
    assert result.results[0].url == f"{_VARIATION_PREFIX}4975019/"


@pytest.mark.asyncio
async def test_search_sends_encoded_query_and_db(respx_mock) -> None:
    search_route = respx_mock.get(_ESEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=_esearch_payload(["1"])),
    )
    respx_mock.get(_ESUMMARY_URL).mock(
        return_value=respx.MockResponse(200, json=_esummary_payload(_record(uid="1"))),
    )

    await _provider().search("BRCA1 c.68_69del", SearchParams(num_results=3))

    params = search_route.calls.last.request.url.params
    assert params["db"] == "clinvar"
    assert params["term"] == "BRCA1 c.68_69del"
    assert params["retmode"] == "json"
    assert params["retmax"] == "3"


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    search_route = respx_mock.get(_ESEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=_esearch_payload([])),
    )

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not search_route.called


@pytest.mark.asyncio
async def test_search_empty_id_list_skips_summary(respx_mock) -> None:
    respx_mock.get(_ESEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=_esearch_payload([])),
    )
    summary_route = respx_mock.get(_ESUMMARY_URL).mock(
        return_value=respx.MockResponse(200, json={"result": {}}),
    )

    result = await _provider().search("zzz-no-match", SearchParams(num_results=5))

    assert result.results == []
    assert not summary_route.called


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    search_route = respx_mock.get(_ESEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=_esearch_payload(["1", "2", "3"])),
    )
    respx_mock.get(_ESUMMARY_URL).mock(
        return_value=respx.MockResponse(
            200,
            json=_esummary_payload(
                _record(uid="1"), _record(uid="2"), _record(uid="3")
            ),
        ),
    )

    await _provider().search("variant", SearchParams(num_results=2))

    assert search_route.calls.last.request.url.params["retmax"] == "2"


@pytest.mark.asyncio
async def test_search_raises_on_api_error(respx_mock) -> None:
    respx_mock.get(_ESEARCH_URL).mock(return_value=respx.MockResponse(500, json={}))

    with pytest.raises(httpx.HTTPStatusError):
        await _provider().search("BARD1", SearchParams(num_results=5))


@pytest.mark.asyncio
async def test_search_raises_on_summary_error(respx_mock) -> None:
    respx_mock.get(_ESEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=_esearch_payload(["1"])),
    )
    respx_mock.get(_ESUMMARY_URL).mock(return_value=respx.MockResponse(502, json={}))

    with pytest.raises(httpx.HTTPStatusError):
        await _provider().search("BARD1", SearchParams(num_results=5))
