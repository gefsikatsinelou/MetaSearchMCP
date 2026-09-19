"""Unit tests for the EBI Ontology Lookup Service (OLS4) provider."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.ols import OlsProvider

_ENDPOINT = "https://www.ebi.ac.uk/ols4/api/search"

_TERM: dict[str, Any] = {
    "iri": "http://id.nlm.nih.gov/mesh/D001241",
    "ontology_name": "mesh",
    "ontology_prefix": "mesh",
    "short_form": "mesh_D001241",
    "obo_id": "mesh:D001241",
    "label": "Aspirin",
    "type": "class",
    "description": ["A non-steroidal anti-inflammatory agent."],
    "exact_synonyms": ["Acetylsalicylic Acid", "ASA"],
    "related_synonyms": ["asa", "Ecotrin"],
    "narrow_synonyms": ["Bayer aspirin"],
    "broad_synonyms": ["Salicylate"],
}

# Ontology-level entry: no short_form, obo_id or ontology_prefix.
_ONTOLOGY: dict[str, Any] = {
    "iri": "http://purl.obolibrary.org/obo/go/extensions/go-plus.ofn",
    "ontology_name": "go",
    "label": "Gene Ontology",
    "type": "ontology",
    "description": ["A framework for describing gene product functions."],
}


def _envelope(docs: list[Any], num_found: int | None = 1234) -> dict[str, Any]:
    """Wrap *docs* in an OLS4 search response envelope."""
    response: dict[str, Any] = {"docs": docs, "start": 0}
    if num_found is not None:
        response["numFound"] = num_found
    return {"response": response, "responseHeader": {"QTime": 0, "status": 0}}


def test_ols_name_tags_and_availability() -> None:
    p = OlsProvider()
    assert p.name == "ols"
    assert p.tags == ["academic", "bio", "medical", "reference"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_ols_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "ols" in registry
    assert registry["ols"].tags == ["academic", "bio", "medical", "reference"]


def test_ols_parse_term() -> None:
    p = OlsProvider()
    result = p._parse(_envelope([_TERM]), limit=5)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Aspirin"
    assert r.url == (
        "https://www.ebi.ac.uk/ols4/ontologies/mesh/terms"
        "?iri=http%3A%2F%2Fid.nlm.nih.gov%2Fmesh%2FD001241"
    )
    assert r.source == "ebi.ac.uk/ols4"
    assert r.provider == "ols"
    assert r.rank == 1
    assert r.snippet == (
        "A non-steroidal anti-inflammatory agent. | Ontology: mesh | "
        "Type: class | Synonyms: Acetylsalicylic Acid, ASA, Ecotrin, "
        "Bayer aspirin"
    )
    assert r.extra["iri"] == "http://id.nlm.nih.gov/mesh/D001241"
    assert r.extra["short_form"] == "mesh_D001241"
    assert r.extra["obo_id"] == "mesh:D001241"
    assert r.extra["ontology_name"] == "mesh"
    assert r.extra["ontology_prefix"] == "mesh"
    assert r.extra["ontology_url"] == "https://www.ebi.ac.uk/ols4/ontologies/mesh"
    assert r.extra["term_url"] == r.url
    assert r.extra["type"] == "class"
    assert r.extra["description"] == ["A non-steroidal anti-inflammatory agent."]
    assert r.extra["synonyms"] == [
        "Acetylsalicylic Acid",
        "ASA",
        "Ecotrin",
        "Bayer aspirin",
        "Salicylate",
    ]
    assert r.extra["exact_synonyms"] == ["Acetylsalicylic Acid", "ASA"]
    assert r.extra["related_synonyms"] == ["asa", "Ecotrin"]
    assert r.extra["narrow_synonyms"] == ["Bayer aspirin"]
    assert r.extra["broad_synonyms"] == ["Salicylate"]
    assert r.extra["total_results"] == 1234


def test_ols_parse_ontology_level_entry() -> None:
    p = OlsProvider()
    r = p._parse(_envelope([_ONTOLOGY])).results[0]

    assert r.title == "Gene Ontology"
    assert r.url == (
        "https://www.ebi.ac.uk/ols4/ontologies/go/terms"
        "?iri=http%3A%2F%2Fpurl.obolibrary.org%2Fobo%2Fgo%2Fextensions%2Fgo-plus.ofn"
    )
    assert r.snippet == (
        "A framework for describing gene product functions. | Ontology: go | "
        "Type: ontology"
    )
    assert r.extra["short_form"] is None
    assert r.extra["obo_id"] is None
    # The ontology name stands in for the missing prefix.
    assert r.extra["ontology_prefix"] == "go"
    assert r.extra["synonyms"] == []


def test_ols_snippet_truncates_long_definition() -> None:
    p = OlsProvider()
    definition = "word " * 80
    item = dict(_TERM, description=[definition])
    r = p._parse(_envelope([item])).results[0]

    assert len(r.snippet) <= 400
    assert r.snippet.startswith("word word")
    assert "…" in r.snippet
    assert "Ontology: mesh" in r.snippet
    assert r.extra["description"] == [" ".join(definition.split())]


def test_ols_parse_skips_documents_without_identity() -> None:
    p = OlsProvider()
    payload = _envelope([{}, {"label": "No IRI"}, {"iri": 7}, "nope", [_TERM], _TERM])
    results = p._parse(payload).results

    assert [r.title for r in results] == ["Aspirin"]
    assert results[0].rank == 1


def test_ols_parse_falls_back_to_iri_title() -> None:
    p = OlsProvider()
    item = {"iri": "http://example.org/term/1", "ontology_name": "example"}
    r = p._parse(_envelope([item])).results[0]

    assert r.title == "http://example.org/term/1"
    assert r.url == (
        "https://www.ebi.ac.uk/ols4/ontologies/example/terms"
        "?iri=http%3A%2F%2Fexample.org%2Fterm%2F1"
    )
    assert r.snippet == "Ontology: example"


def test_ols_parse_respects_limit() -> None:
    p = OlsProvider()
    docs = [dict(_TERM, label=f"Term {n}") for n in range(5)]
    payload = _envelope(docs)

    assert len(p._parse(payload, limit=2).results) == 2
    assert len(p._parse(payload).results) == 5
    assert [r.rank for r in p._parse(payload, limit=2).results] == [1, 2]


def test_ols_parse_empty_and_malformed() -> None:
    p = OlsProvider()
    assert p._parse(_envelope([])).results == []
    assert p._parse({}).results == []
    assert p._parse({"response": "nope"}).results == []
    assert p._parse({"response": {"docs": "nope"}}).results == []
    assert p._parse({"response": {"docs": [1, 2]}}).results == []
    assert p._parse([]).results == []
    assert p._parse(None).results == []


def test_ols_parse_without_num_found() -> None:
    p = OlsProvider()
    r = p._parse(_envelope([_TERM], num_found=None)).results[0]
    assert r.extra["total_results"] is None


def test_ols_parse_ignores_odd_field_types() -> None:
    p = OlsProvider()
    payload = _envelope(
        [
            {
                "iri": "  http://example.org/x  ",
                "label": 42,
                "ontology_name": 7,
                "ontology_prefix": None,
                "type": "",
                "description": "not a list",
                "exact_synonyms": ["Syn", 5, ""],
                "related_synonyms": "nope",
            }
        ],
        num_found=None,
    )
    r = p._parse(payload).results[0]

    assert r.title == "http://example.org/x"
    assert r.snippet == "Synonyms: Syn"
    assert r.extra["ontology_name"] is None
    assert r.extra["ontology_prefix"] is None
    assert r.extra["ontology_url"] is None
    assert r.extra["type"] is None
    assert r.extra["description"] == []
    assert r.extra["synonyms"] == ["Syn"]


def test_ols_helpers() -> None:
    from metasearchmcp.providers.ols import (
        _clean,
        _int,
        _ontology_url,
        _strings,
        _synonyms,
        _term_url,
        _truncate,
    )

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _int(1234) == 1234
    assert _int(True) is None
    assert _int("1234") is None
    assert _strings(["a", 5, "", "b"]) == ["a", "b"]
    assert _strings("nope") == []
    assert _truncate("abc", 5) == "abc"
    assert _truncate("abcdef", 5) == "abcd…"
    assert _synonyms(
        {
            "exact_synonyms": ["Aspirin", "ASA"],
            "related_synonyms": ["aspirin", "ASA", "Ecotrin"],
        }
    ) == ["Aspirin", "ASA", "Ecotrin"]
    assert _synonyms({}) == []
    assert _term_url({"iri": "http://x/y", "ontology_name": "go"}) == (
        "https://www.ebi.ac.uk/ols4/ontologies/go/terms?iri=http%3A%2F%2Fx%2Fy"
    )
    assert _term_url({"iri": "http://x/y"}) == "http://x/y"
    assert _term_url({}) == ""
    assert _ontology_url({"ontology_name": "go"}) == (
        "https://www.ebi.ac.uk/ols4/ontologies/go"
    )
    assert _ontology_url({}) == ""


async def test_ols_search_sends_expected_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope([_TERM, _ONTOLOGY]))
    )

    result = await OlsProvider().search("aspirin", SearchParams(num_results=5))

    assert route.called
    params = route.calls[0].request.url.params
    assert params["q"] == "aspirin"
    assert params["rows"] == "5"
    assert params["start"] == "0"

    assert [r.title for r in result.results] == ["Aspirin", "Gene Ontology"]


async def test_ols_search_caps_limit_to_api_maximum(respx_mock) -> None:
    docs = [dict(_TERM, label=f"Term {n}") for n in range(150)]
    respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope(docs))
    )

    provider = OlsProvider()
    provider._max_results = 1000
    result = await provider.search("cell", SearchParams(num_results=50))
    assert len(result.results) == 50

    provider._max_results = 1
    result = await provider.search("cell", SearchParams(num_results=50))
    assert len(result.results) == 1


async def test_ols_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT)

    result = await OlsProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_ols_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(503))

    with pytest.raises(httpx.HTTPStatusError):
        await OlsProvider().search("aspirin", SearchParams())
