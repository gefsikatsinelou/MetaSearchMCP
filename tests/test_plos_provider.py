"""Unit tests for the keyless PLOS open-access research search provider."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.plos import PlosProvider

_ENDPOINT = "https://api.plos.org/search"


def _response(docs: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a PLOS search envelope around *docs*."""
    return {"response": {"numFound": len(docs), "start": 0, "docs": docs}}


_MALARIA: dict[str, Any] = _response(
    [
        {
            "id": "10.1371/journal.pone.0004050",
            "journal": "PLoS ONE",
            "publication_date": "2008-12-30T00:00:00Z",
            "author_display": ["Bernard A. Okech", "Isaac K. Mwobobia"],
            "abstract": ["  Use of Integrated\n Malaria Management  "],
            "title_display": (
                "Use of Integrated Malaria Management Reduces Malaria in Kenya"
            ),
        },
        {
            "id": "10.1371/journal.pgph.0000609",
            "journal": "PLOS Global Public Health",
            "publication_date": "2022-06-09T00:00:00Z",
            "author_display": ["Ravindra P. Rannan-Eliya"],
            "abstract": ["Financing for malaria elimination"],
            "title_display": "Financing malaria",
        },
    ]
)


def test_plos_name_tags_and_availability() -> None:
    p = PlosProvider()
    assert p.name == "plos"
    assert p.tags == ["academic", "web"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_plos_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "plos" in registry
    assert registry["plos"].tags == ["academic", "web"]


def test_plos_parse_single_article() -> None:
    p = PlosProvider()
    result = p._parse(_MALARIA, limit=5)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Use of Integrated Malaria Management Reduces Malaria in Kenya"
    assert r.url == "https://doi.org/10.1371/journal.pone.0004050"
    assert r.source == "plos"
    assert r.provider == "plos"
    assert r.rank == 1
    assert r.published_date is None
    assert (
        r.snippet == "PLoS ONE | 2008-12-30 | Bernard A. Okech, Isaac K. Mwobobia"
        " — Use of Integrated Malaria Management"
    )
    assert r.extra["doi"] == "10.1371/journal.pone.0004050"
    assert r.extra["journal"] == "PLoS ONE"
    assert r.extra["authors"] == ["Bernard A. Okech", "Isaac K. Mwobobia"]
    assert r.extra["publication_date"] == "2008-12-30"


def test_plos_parse_preserves_order_and_ranks() -> None:
    p = PlosProvider()
    result = p._parse(_MALARIA)

    assert [r.title for r in result.results] == [
        "Use of Integrated Malaria Management Reduces Malaria in Kenya",
        "Financing malaria",
    ]
    assert [r.rank for r in result.results] == [1, 2]


def test_plos_snippet_appends_et_al_beyond_five_authors() -> None:
    p = PlosProvider()
    doc = {
        "id": "10.1/x",
        "title_display": "Many authors",
        "author_display": [f"Author {n}" for n in range(1, 8)],
    }
    snippet = p._parse(_response([doc])).results[0].snippet

    assert "Author 1, Author 2, Author 3, Author 4, Author 5 et al." in snippet
    assert "Author 6" not in snippet


def test_plos_abstract_html_is_stripped() -> None:
    p = PlosProvider()
    doc = {
        "id": "10.1/x",
        "title_display": "Tagged",
        "abstract": ["<jats:p>Hello</jats:p> <b>world</b>"],
    }
    snippet = p._parse(_response([doc])).results[0].snippet

    assert snippet == "Hello world"


def test_plos_parse_skips_records_without_title_or_doi() -> None:
    p = PlosProvider()
    payload = _response(
        [
            {},
            {"title_display": "No DOI"},
            {"id": "10.1/x"},
            {"id": "10.1/y", "title_display": "  Kept  "},
        ]
    )
    results = p._parse(payload).results

    assert [r.title for r in results] == ["Kept"]
    assert results[0].rank == 1
    assert results[0].snippet == ""


def test_plos_parse_respects_limit() -> None:
    p = PlosProvider()
    assert len(p._parse(_MALARIA, limit=1).results) == 1
    assert len(p._parse(_MALARIA).results) == 2


def test_plos_parse_empty_and_malformed() -> None:
    p = PlosProvider()
    assert p._parse({}).results == []
    assert p._parse({"response": {}}).results == []
    assert p._parse({"response": {"docs": "nope"}}).results == []
    assert p._parse({"response": {"docs": []}}).results == []
    assert p._parse(_response([])).results == []
    assert p._parse([_MALARIA]).results == []
    assert p._parse("nope").results == []
    assert p._parse(None).results == []


def test_plos_helpers() -> None:
    from metasearchmcp.providers.plos import _clean, _first_text

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _clean(42) == ""
    assert _first_text(["", " x "]) == "x"
    assert _first_text(" plain ") == "plain"
    assert _first_text(None) == ""
    assert PlosProvider._authors([" a ", "b", "", 7]) == ["a", "b"]
    assert PlosProvider._authors("nope") == []


def test_plos_escape_solr_reserved_characters() -> None:
    assert PlosProvider._escape("machine learning") == "machine learning"
    assert PlosProvider._escape("CRISPR:gene") == "CRISPR\\:gene"
    assert PlosProvider._escape("C++ (x)") == "C\\+\\+ \\(x\\)"


async def test_plos_search_sends_expected_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_MALARIA)
    )

    result = await PlosProvider().search("malaria", SearchParams(num_results=5))

    assert route.called
    request = route.calls[0].request
    assert request.url.params["q"] == "malaria"
    assert request.url.params["rows"] == "5"
    assert request.url.params["wt"] == "json"
    assert "title_display" in request.url.params["fl"]
    assert len(result.results) == 2


async def test_plos_search_escapes_reserved_characters(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_MALARIA)
    )

    await PlosProvider().search("CRISPR:gene", SearchParams())

    assert route.calls[0].request.url.params["q"] == "CRISPR\\:gene"


async def test_plos_search_no_matches_returns_empty(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_response([]))
    )

    result = await PlosProvider().search("zzz", SearchParams())
    assert result.results == []


async def test_plos_search_respects_result_limits(respx_mock) -> None:
    docs = [{"id": f"10.1/{n}", "title_display": f"Article {n}"} for n in range(1, 41)]
    respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_response(docs))
    )

    provider = PlosProvider()
    provider._max_results = 1000
    result = await provider.search("x", SearchParams(num_results=30))
    assert len(result.results) == 30

    provider._max_results = 1
    result = await provider.search("x", SearchParams(num_results=30))
    assert len(result.results) == 1


async def test_plos_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT)

    result = await PlosProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_plos_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(500))

    with pytest.raises(httpx.HTTPStatusError):
        await PlosProvider().search("malaria", SearchParams())
