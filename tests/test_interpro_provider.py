"""Unit tests for the InterPro protein family/domain search provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.interpro import InterProProvider

_SEARCH_URL = "https://www.ebi.ac.uk/interpro/api/entry/interpro/"
_DETAIL_PREFIX = "https://www.ebi.ac.uk/interpro/entry/InterPro/"

_PAYLOAD = {
    "count": 3,
    "next": None,
    "previous": None,
    "results": [
        {
            "metadata": {
                "accession": "IPR000023",
                "name": "Phosphofructokinase domain",
                "source_database": "interpro",
                "type": "domain",
                "integrated": None,
                "member_databases": {"pfam": {"PF00365": "Phosphofructokinase"}},
                "go_terms": [
                    {
                        "identifier": "GO:0003872",
                        "name": "6-phosphofructokinase activity",
                        "category": {"code": "F", "name": "molecular_function"},
                    },
                ],
            },
        },
        {
            "metadata": {
                "accession": "IPR000333",
                "name": "Ser/Thr protein kinase, TGFB receptor",
                "source_database": "interpro",
                "type": "family",
                "member_databases": {
                    "panther": {"PTHR23255": "TGF-BETA RECEPTOR"},
                    "prints": {"PR00653": "ACTIVIN2R"},
                },
                "go_terms": [
                    {
                        "identifier": "GO:0004675",
                        "name": "kinase activity",
                        "category": {"code": "F"},
                    },
                    {
                        "identifier": "GO:0016020",
                        "name": "membrane",
                        "category": {"code": "C"},
                    },
                ],
            },
        },
        {"metadata": {"name": "Skipped: no accession"}},
    ],
}


def _mock(respx_mock, payload: object = _PAYLOAD):
    """Mock the InterPro search endpoint with *payload*."""
    return respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=payload),
    )


def _provider() -> InterProProvider:
    """Return a fresh provider instance for each test."""
    return InterProProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "interpro"
    assert p.tags == ["academic", "web", "bio", "science"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "interpro" in registry
    assert registry["interpro"].tags == ["academic", "web", "bio", "science"]


@pytest.mark.asyncio
async def test_search_builds_structured_result(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("kinase", SearchParams(num_results=10))
    first = result.results[0]

    assert first.title == "Phosphofructokinase domain"
    assert first.url == f"{_DETAIL_PREFIX}IPR000023"
    assert first.source == "ebi.ac.uk"
    assert first.provider == "interpro"
    assert first.rank == 1
    assert first.snippet == (
        "Type: domain | Signatures: pfam:PF00365 (Phosphofructokinase) | "
        "GO: 6-phosphofructokinase activity (GO:0003872)"
    )
    assert first.extra == {
        "accession": "IPR000023",
        "type": "domain",
        "source_database": "interpro",
        "integrated": None,
        "member_databases": [
            {"database": "pfam", "accession": "PF00365", "name": "Phosphofructokinase"},
        ],
        "go_terms": [
            {
                "identifier": "GO:0003872",
                "name": "6-phosphofructokinase activity",
                "category": "molecular_function",
            },
        ],
    }

    second = result.results[1]
    assert second.title == "Ser/Thr protein kinase, TGFB receptor"
    assert second.url == f"{_DETAIL_PREFIX}IPR000333"
    assert second.snippet == (
        "Type: family | Signatures: panther:PTHR23255 (TGF-BETA RECEPTOR); "
        "prints:PR00653 (ACTIVIN2R) | GO: kinase activity (GO:0004675); "
        "membrane (GO:0016020)"
    )
    assert second.extra["member_databases"] == [
        {"database": "panther", "accession": "PTHR23255", "name": "TGF-BETA RECEPTOR"},
        {"database": "prints", "accession": "PR00653", "name": "ACTIVIN2R"},
    ]
    # A GO term whose category has no name falls back to its code.
    assert second.extra["go_terms"][1]["category"] == "C"


@pytest.mark.asyncio
async def test_search_degrades_on_missing_fields(respx_mock) -> None:
    _mock(respx_mock, {"results": [{"metadata": {"accession": "IPR9", "name": "Min"}}]})

    result = await _provider().search("min", SearchParams(num_results=5))
    only = result.results[0]

    assert only.url == f"{_DETAIL_PREFIX}IPR9"
    assert only.snippet == ""
    assert only.extra["type"] is None
    assert only.extra["source_database"] is None
    assert only.extra["integrated"] is None
    assert only.extra["member_databases"] == []
    assert only.extra["go_terms"] == []


@pytest.mark.asyncio
async def test_search_skips_incomplete_and_malformed_entries(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("kinase", SearchParams(num_results=10))

    assert [r.title for r in result.results] == [
        "Phosphofructokinase domain",
        "Ser/Thr protein kinase, TGFB receptor",
    ]
    assert [r.rank for r in result.results] == [1, 2]


@pytest.mark.asyncio
async def test_search_deduplicates_by_accession(respx_mock) -> None:
    duplicate = {"metadata": {"accession": "IPR1", "name": "Same entry"}}
    _mock(respx_mock, {"results": [dict(duplicate), dict(duplicate)]})

    result = await _provider().search("same", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["Same entry"]


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("kinase", SearchParams(num_results=1))

    assert [r.title for r in result.results] == ["Phosphofructokinase domain"]


@pytest.mark.asyncio
async def test_search_sends_query_params(respx_mock) -> None:
    route = _mock(respx_mock)

    await _provider().search("kinase", SearchParams(num_results=7))

    params = route.calls.last.request.url.params
    assert params["search"] == "kinase"
    assert params["page_size"] == "7"


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    route = _mock(respx_mock)

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_handles_unexpected_payload_shapes(respx_mock) -> None:
    for payload in (
        ["not", "a", "mapping"],
        {},
        {"results": None},
        {"results": "nope"},
        {"results": [{"metadata": None}]},
        {"results": ["not-a-mapping"]},
        {"results": [{"metadata": {"accession": "IPR1"}}]},
    ):
        respx_mock.get(_SEARCH_URL).mock(
            return_value=respx.MockResponse(200, json=payload),
        )
        result = await _provider().search("kinase", SearchParams(num_results=5))
        assert result.results == []


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("kinase", SearchParams(num_results=5))
