"""Unit tests for the keyless Open Targets Platform search provider."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.open_targets import OpenTargetsProvider

_ENDPOINT = "https://api.platform.opentargets.org/api/v4/graphql"

_TARGET: dict[str, Any] = {
    "id": "ENSG00000139618",
    "name": "BRCA2",
    "entity": "target",
    "description": "BRCA2 DNA repair associated [Source:HGNC Symbol;Acc:HGNC:1101]",
}

_DRUG: dict[str, Any] = {
    "id": "CHEMBL941",
    "name": "IMATINIB",
    "entity": "drug",
    "description": (
        "Small molecule drug with a maximum clinical stage of Approval "
        "(across all indications)."
    ),
}

_DISEASE: dict[str, Any] = {
    "id": "MONDO_0007254",
    "name": "breast cancer",
    "entity": "disease",
    "description": "A primary or metastatic malignant neoplasm involving the breast.",
}


def _payload(hits: list[dict[str, Any]], total: int | None = None) -> dict[str, Any]:
    """Wrap *hits* in the Open Targets GraphQL ``search`` response shape."""
    return {
        "data": {
            "search": {
                "total": len(hits) if total is None else total,
                "hits": hits,
            },
        },
    }


def test_opentargets_name_tags_and_availability() -> None:
    p = OpenTargetsProvider()
    assert p.name == "opentargets"
    assert p.tags == ["bio", "medical", "drugs", "academic"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_opentargets_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "opentargets" in registry
    assert registry["opentargets"].tags == ["bio", "medical", "drugs", "academic"]


def test_opentargets_parse_single_hit() -> None:
    p = OpenTargetsProvider()
    result = p._parse(_payload([_TARGET]), limit=5)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "BRCA2"
    assert r.url == "https://platform.opentargets.org/target/ENSG00000139618"
    assert r.source == "platform.opentargets.org"
    assert r.provider == "opentargets"
    assert r.rank == 1
    assert r.snippet == (
        "BRCA2 DNA repair associated [Source:HGNC Symbol;Acc:HGNC:1101] | Type: target"
    )
    assert r.extra["entity"] == "target"
    assert r.extra["entity_id"] == "ENSG00000139618"
    assert r.extra["total_matches"] == 1


def test_opentargets_parse_without_description() -> None:
    p = OpenTargetsProvider()
    payload = _payload([{"id": "ENSG00000000001", "name": "FOO", "entity": "target"}])
    r = p._parse(payload).results[0]

    assert r.snippet == "Type: target"
    assert r.extra["description"] is None
    assert r.url == "https://platform.opentargets.org/target/ENSG00000000001"


def test_opentargets_parse_entity_urls() -> None:
    p = OpenTargetsProvider()
    result = p._parse(_payload([_TARGET, _DRUG, _DISEASE]))

    assert [r.url for r in result.results] == [
        "https://platform.opentargets.org/target/ENSG00000139618",
        "https://platform.opentargets.org/drug/CHEMBL941",
        "https://platform.opentargets.org/disease/MONDO_0007254",
    ]


def test_opentargets_parse_preserves_order_and_ranks() -> None:
    p = OpenTargetsProvider()
    result = p._parse(_payload([_DRUG, _TARGET, _DISEASE]))

    assert [r.extra["entity"] for r in result.results] == ["drug", "target", "disease"]
    assert [r.rank for r in result.results] == [1, 2, 3]


def test_opentargets_parse_skips_unusable_records() -> None:
    p = OpenTargetsProvider()
    payload = _payload(
        [
            {},
            {"name": ""},
            {"id": "ENSG00000000009"},
            {"name": "  Air  ", "id": "CHEMBL1", "entity": "drug"},
        ],
    )
    results = p._parse(payload).results

    assert [r.title for r in results] == ["ENSG00000000009", "Air"]
    assert [r.rank for r in results] == [1, 2]


def test_opentargets_parse_respects_limit() -> None:
    p = OpenTargetsProvider()
    hits = [dict(_TARGET, id=f"ENSG0000000000{n}", name=f"G{n}") for n in range(1, 6)]

    assert len(p._parse(_payload(hits), limit=1).results) == 1
    assert len(p._parse(_payload(hits)).results) == 5


def test_opentargets_parse_empty_and_malformed() -> None:
    p = OpenTargetsProvider()
    assert p._parse({}).results == []
    assert p._parse([]).results == []
    assert p._parse("nope").results == []
    assert p._parse(None).results == []
    assert p._parse({"data": {}}).results == []
    assert p._parse({"data": {"search": {}}}).results == []
    assert p._parse({"data": {"search": {"hits": "nope"}}}).results == []
    assert p._parse({"data": {"search": {"hits": []}}}).results == []
    malformed = {"data": {"search": {"total": 3, "hits": [_TARGET, "nope", 3]}}}
    assert p._parse(malformed).results[0].title == "BRCA2"


def test_opentargets_helpers() -> None:
    from metasearchmcp.providers.open_targets import _clean, _entity_url, _int

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _clean(42) == ""
    assert _int(5) == 5
    assert _int(5.0) == 5
    assert _int(True) is None
    assert _int("5") is None
    assert _int(None) is None
    assert _entity_url("drug", "CHEMBL941") == (
        "https://platform.opentargets.org/drug/CHEMBL941"
    )
    assert _entity_url("weird", "X") == "https://platform.opentargets.org/target/X"


async def test_opentargets_search_sends_expected_request(respx_mock) -> None:
    route = respx_mock.post(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_payload([_TARGET])),
    )

    result = await OpenTargetsProvider().search("BRCA2", SearchParams(num_results=5))

    assert route.called
    body = json.loads(route.calls[0].request.content)
    assert body["variables"]["queryString"] == "BRCA2"
    assert body["variables"]["entityNames"] == ["target", "disease", "drug"]
    assert body["variables"]["size"] == 5
    assert "search(" in body["query"]
    assert [r.title for r in result.results] == ["BRCA2"]


async def test_opentargets_search_no_matches_returns_empty(respx_mock) -> None:
    respx_mock.post(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_payload([])),
    )

    result = await OpenTargetsProvider().search("zzzqqq", SearchParams())
    assert result.results == []


async def test_opentargets_search_respects_result_limits(respx_mock) -> None:
    hits = [dict(_TARGET, id=f"ENSG{n}", name=f"G{n}") for n in range(1, 41)]
    respx_mock.post(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_payload(hits, total=len(hits))),
    )

    provider = OpenTargetsProvider()
    provider._max_results = 1000
    result = await provider.search("gene", SearchParams(num_results=30))
    assert len(result.results) == 30

    provider._max_results = 1
    result = await provider.search("gene", SearchParams(num_results=30))
    assert len(result.results) == 1


async def test_opentargets_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.post(_ENDPOINT)

    result = await OpenTargetsProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_opentargets_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.post(_ENDPOINT).mock(return_value=respx.MockResponse(500))

    with pytest.raises(httpx.HTTPStatusError):
        await OpenTargetsProvider().search("BRCA2", SearchParams())
