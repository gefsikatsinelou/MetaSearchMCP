"""Unit tests for the NLM Clinical Tables medical code search provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams, SearchResult
from metasearchmcp.providers.medical_codes import (
    _CODE_SYSTEMS,
    MedicalCodesProvider,
    _rows,
    _text,
)

_CM_URL = "https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search"
_ICD11_URL = "https://clinicaltables.nlm.nih.gov/api/icd11_codes/v3/search"
_HCPCS_URL = "https://clinicaltables.nlm.nih.gov/api/hcpcs/v3/search"
_LOOKUP = "https://clinicaltables.nlm.nih.gov/demo.html"
_ALL_URLS = (_CM_URL, _ICD11_URL, _HCPCS_URL)


def _provider() -> MedicalCodesProvider:
    """Return a fresh provider instance for each test."""
    return MedicalCodesProvider()


def _payload(*rows: tuple[str, str]) -> list:
    """Build a Clinical Tables positional response for the given code rows."""
    return [len(rows), [row[0] for row in rows], None, [list(row) for row in rows]]


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "medical_codes"
    assert p.tags == ["medical", "health", "reference"]
    assert "No API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "medical_codes" in registry
    assert registry["medical_codes"].tags == ["medical", "health", "reference"]


def test_code_systems_cover_expected_databases() -> None:
    assert [(label, db) for label, db, _ in _CODE_SYSTEMS] == [
        ("ICD-10-CM", "icd10cm"),
        ("ICD-11", "icd11_codes"),
        ("HCPCS", "hcpcs"),
    ]
    extra = {db: params for _, db, params in _CODE_SYSTEMS}
    assert extra["icd10cm"] == {"sf": "code,name"}
    assert extra["icd11_codes"] == {}
    assert extra["hcpcs"] == {}


def test_text_collapses_whitespace_and_ignores_non_strings() -> None:
    assert _text("  type 2\n  diabetes ") == "type 2 diabetes"
    assert _text(None) == ""
    assert _text(5) == ""


def test_rows_extracts_code_name_pairs() -> None:
    payload = _payload(("E11.9", "Type 2 diabetes"), ("  E10.9 ", " Type 1  diabetes "))

    assert _rows(payload) == [
        ("E11.9", "Type 2 diabetes"),
        ("E10.9", "Type 1 diabetes"),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        "nope",
        None,
        [0, [], None],
        [1, ["X"], None, "not-a-list"],
        [1, ["X"], None, [["only-code"]]],
        [1, ["X"], None, [["", "no code"]]],
        [1, ["X"], None, [["C1", "  "]]],
    ],
)
def test_rows_ignores_malformed_payloads(payload) -> None:
    assert _rows(payload) == []


def test_interleave_round_robins_and_truncates() -> None:
    def hit(title: str) -> SearchResult:
        return SearchResult(title=title, url=f"https://example.com/{title}")

    groups = [
        [hit("a1"), hit("a2")],
        [hit("b1")],
        [hit("c1"), hit("c2"), hit("c3")],
    ]

    merged = MedicalCodesProvider._interleave(groups, 4)

    assert [r.title for r in merged] == ["a1", "b1", "c1", "a2"]
    assert MedicalCodesProvider._interleave([], 5) == []


@pytest.mark.asyncio
async def test_search_merges_and_interleaves_systems(respx_mock) -> None:
    cm = respx_mock.get(_CM_URL).mock(
        return_value=respx.MockResponse(
            200,
            json=_payload(
                ("E11.9", "Type 2 diabetes mellitus without complications"),
                ("E10.9", "Type 1 diabetes mellitus without complications"),
            ),
        ),
    )
    icd11 = respx_mock.get(_ICD11_URL).mock(
        return_value=respx.MockResponse(
            200,
            json=_payload(("5A61.5", "Central diabetes insipidus")),
        ),
    )
    hcpcs = respx_mock.get(_HCPCS_URL).mock(
        return_value=respx.MockResponse(
            200,
            json=_payload(("E0601", "Continuous positive airway pressure device")),
        ),
    )

    result = await _provider().search("diabetes", SearchParams(num_results=10))

    assert cm.called and icd11.called and hcpcs.called
    for route in (cm, icd11, hcpcs):
        params = route.calls.last.request.url.params
        assert params["terms"] == "diabetes"
        assert params["maxList"] == "10"
    assert cm.calls.last.request.url.params["sf"] == "code,name"
    assert "sf" not in icd11.calls.last.request.url.params
    assert "sf" not in hcpcs.calls.last.request.url.params

    assert [r.extra["code"] for r in result.results] == [
        "E11.9",
        "5A61.5",
        "E0601",
        "E10.9",
    ]
    assert [r.rank for r in result.results] == [1, 2, 3, 4]
    assert [r.extra["system"] for r in result.results] == [
        "ICD-10-CM",
        "ICD-11",
        "HCPCS",
        "ICD-10-CM",
    ]

    first = result.results[0]
    assert first.title == "E11.9 — Type 2 diabetes mellitus without complications"
    assert first.url == f"{_LOOKUP}?db=icd10cm&terms=E11.9"
    assert first.source == "clinicaltables.nlm.nih.gov"
    assert first.provider == "medical_codes"
    assert first.snippet == (
        "ICD-10-CM code E11.9: Type 2 diabetes mellitus without complications"
    )
    assert first.extra == {
        "code": "E11.9",
        "name": "Type 2 diabetes mellitus without complications",
        "system": "ICD-10-CM",
        "database": "icd10cm",
    }


@pytest.mark.asyncio
async def test_search_normalizes_query_whitespace(respx_mock) -> None:
    routes = [
        respx_mock.get(url).mock(return_value=respx.MockResponse(200, json=_payload()))
        for url in _ALL_URLS
    ]

    await _provider().search("  diabetes \n ", SearchParams(num_results=5))

    for route in routes:
        assert route.calls.last.request.url.params["terms"] == "diabetes"


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    respx_mock.get(_CM_URL).mock(
        return_value=respx.MockResponse(
            200,
            json=_payload(
                ("E11.9", "Type 2 diabetes"),
                ("E10.9", "Type 1 diabetes"),
                ("O24.4", "Gestational diabetes"),
            ),
        ),
    )
    respx_mock.get(_ICD11_URL).mock(
        return_value=respx.MockResponse(
            200, json=_payload(("5A61.5", "Diabetes insipidus"))
        )
    )
    respx_mock.get(_HCPCS_URL).mock(
        return_value=respx.MockResponse(200, json=_payload(("E0601", "CPAP device")))
    )

    result = await _provider().search("diabetes", SearchParams(num_results=2))

    assert [r.extra["code"] for r in result.results] == ["E11.9", "5A61.5"]
    assert [r.rank for r in result.results] == [1, 2]


@pytest.mark.asyncio
async def test_result_urls_are_unique_per_code(respx_mock) -> None:
    respx_mock.get(_CM_URL).mock(
        return_value=respx.MockResponse(
            200,
            json=_payload(("E11.9", "Type 2 diabetes"), ("E10.9", "Type 1 diabetes")),
        ),
    )
    respx_mock.get(_ICD11_URL).mock(
        return_value=respx.MockResponse(
            200, json=_payload(("5A61.5", "Diabetes insipidus"))
        )
    )
    respx_mock.get(_HCPCS_URL).mock(
        return_value=respx.MockResponse(200, json=_payload(("E0601", "CPAP device")))
    )

    result = await _provider().search("diabetes", SearchParams(num_results=10))

    urls = [r.url for r in result.results]
    assert len(urls) == len(set(urls))
    assert f"{_LOOKUP}?db=icd10cm&terms=E11.9" in urls
    assert f"{_LOOKUP}?db=hcpcs&terms=E0601" in urls


@pytest.mark.asyncio
async def test_search_blank_query_skips_all_requests(respx_mock) -> None:
    routes = [
        respx_mock.get(url).mock(return_value=respx.MockResponse(200, json=_payload()))
        for url in _ALL_URLS
    ]

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not any(route.called for route in routes)


@pytest.mark.asyncio
async def test_search_with_no_matches_returns_empty(respx_mock) -> None:
    for url in _ALL_URLS:
        respx_mock.get(url).mock(
            return_value=respx.MockResponse(200, json=_payload()),
        )

    result = await _provider().search("zzzzzz", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [{}, [], "nope", [1, ["X"], None, "not-a-list"], [9, [], None, [[1, 2]]]],
)
async def test_search_tolerates_unexpected_payloads(respx_mock, payload) -> None:
    for url in _ALL_URLS:
        respx_mock.get(url).mock(return_value=respx.MockResponse(200, json=payload))

    result = await _provider().search("diabetes", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_CM_URL).mock(return_value=respx.MockResponse(503))
    for url in _ALL_URLS[1:]:
        respx_mock.get(url).mock(return_value=respx.MockResponse(200, json=_payload()))

    with pytest.raises(HTTPStatusError):
        await _provider().search("diabetes", SearchParams(num_results=5))
