"""Unit tests for the RCSB PDB structure search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.rcsb_pdb import RcsbPdbProvider

_SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
_GRAPHQL_URL = "https://data.rcsb.org/graphql"

_SEARCH_RESPONSE: dict[str, object] = {
    "query_id": "a174f96a-a259-4291-b6de-a87cf921076d",
    "result_type": "entry",
    "total_count": 9171,
    "result_set": [
        {"identifier": "4HHB", "score": 1.0},
        {"identifier": "2pgh", "score": 0.9995},
        "junk",
        {"identifier": ""},
    ],
}

_GRAPHQL_RESPONSE: dict[str, object] = {
    "data": {
        "entries": [
            {
                "rcsb_id": "4HHB",
                "struct": {
                    "title": (
                        "THE CRYSTAL STRUCTURE OF HUMAN DEOXYHAEMOGLOBIN "
                        "AT 1.74 ANGSTROMS RESOLUTION"
                    ),
                },
                "exptl": [{"method": "X-RAY DIFFRACTION"}],
                "rcsb_entry_info": {
                    "resolution_combined": [1.74],
                    "polymer_entity_count": 2,
                    "deposited_polymer_monomer_count": 574,
                    "experimental_method": "X-ray",
                },
                "rcsb_accession_info": {
                    "initial_release_date": "1984-07-17T00:00:00Z",
                },
                "rcsb_primary_citation": {
                    "rcsb_authors": [
                        "Fermi, G.",
                        "Perutz, M.F.",
                        "Shaanan, B.",
                        "Fourme, R.",
                    ],
                    "year": 1984,
                    "journal_abbrev": "J.Mol.Biol.",
                },
            },
            {
                # Missing title -> fallback label; method from `exptl`;
                # string year -> ignored; no usable resolution.
                "rcsb_id": "2PGH",
                "struct": {"title": ""},
                "exptl": [{"method": "X-RAY DIFFRACTION"}],
                "rcsb_entry_info": {
                    "resolution_combined": None,
                    "polymer_entity_count": 2,
                    "deposited_polymer_monomer_count": 574,
                    "experimental_method": None,
                },
                "rcsb_accession_info": {
                    "initial_release_date": "1994-11-30T00:00:00Z",
                },
                "rcsb_primary_citation": {
                    "rcsb_authors": "Katz, D.S.",
                    "year": "1994",
                    "journal_abbrev": "Nature",
                },
            },
            # Not referenced by the search response -> ignored.
            {"rcsb_id": "1XYZ", "struct": {"title": "EXTRA ENTRY"}},
            "junk",
        ],
    },
}


def _provider() -> RcsbPdbProvider:
    return RcsbPdbProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "rcsb_pdb"
    assert p.tags == ["academic", "web", "bio", "protein", "structure"]
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "rcsb_pdb" in registry
    assert registry["rcsb_pdb"].tags == [
        "academic",
        "web",
        "bio",
        "protein",
        "structure",
    ]


def test_parse_search_orders_and_normalizes_ids() -> None:
    hits = RcsbPdbProvider._parse_search(_SEARCH_RESPONSE)
    assert hits == [("4HHB", 1.0), ("2PGH", 0.9995)]


def test_parse_search_empty_and_malformed() -> None:
    assert RcsbPdbProvider._parse_search({}) == []
    assert RcsbPdbProvider._parse_search({"result_set": "nope"}) == []
    assert RcsbPdbProvider._parse_search({"result_set": [42, None]}) == []
    assert RcsbPdbProvider._parse_search("junk") == []


def test_detail_map_indexes_by_pdb_id() -> None:
    mapping = RcsbPdbProvider._detail_map(_GRAPHQL_RESPONSE)
    assert set(mapping) == {"4HHB", "2PGH", "1XYZ"}
    assert mapping["4HHB"]["rcsb_id"] == "4HHB"
    assert RcsbPdbProvider._detail_map({}) == {}
    assert RcsbPdbProvider._detail_map({"data": "nope"}) == {}
    assert RcsbPdbProvider._detail_map({"data": {"entries": "nope"}}) == {}


def test_assemble_builds_full_result() -> None:
    hits = RcsbPdbProvider._parse_search(_SEARCH_RESPONSE)
    result = _provider()._assemble(hits, _GRAPHQL_RESPONSE, 9171, limit=10)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title.startswith("THE CRYSTAL STRUCTURE OF HUMAN DEOXYHAEMOGLOBIN")
    assert r.url == "https://www.rcsb.org/structure/4HHB"
    assert r.source == "rcsb.org"
    assert r.provider == "rcsb_pdb"
    assert r.rank == 1
    assert r.published_date == "1984-07-17"
    assert "Method: X-ray" in r.snippet
    assert "Resolution: 1.74 A" in r.snippet
    assert "Polymer entities: 2" in r.snippet
    assert "Residues: 574" in r.snippet
    assert "Released: 1984-07-17" in r.snippet
    assert "Fermi, G., Perutz, M.F., Shaanan, B. et al." in r.snippet
    assert "(J.Mol.Biol. 1984)" in r.snippet
    assert r.extra["pdb_id"] == "4HHB"
    assert r.extra["resolution_angstrom"] == 1.74
    assert r.extra["polymer_entity_count"] == 2
    assert r.extra["deposited_polymer_monomer_count"] == 574
    assert r.extra["journal"] == "J.Mol.Biol."
    assert r.extra["year"] == 1984
    assert r.extra["total_results"] == 9171


def test_assemble_handles_missing_detail_and_fallbacks() -> None:
    result = _provider()._assemble(
        [("4HHB", 1.0), ("2PGH", 0.9995)],
        _GRAPHQL_RESPONSE,
        None,
        limit=10,
    )

    second = result.results[1]
    # Empty struct title -> labelled fallback.
    assert second.title == "PDB entry 2PGH"
    assert second.rank == 2
    # experimental_method is null -> falls back to the raw exptl array.
    assert second.extra["experimental_method"] == "X-RAY DIFFRACTION"
    assert second.extra["resolution_angstrom"] is None
    assert second.extra["year"] is None
    assert second.extra["authors"] == ["Katz, D.S."]
    assert "Resolution:" not in second.snippet
    assert "(Nature" not in second.snippet


def test_assemble_missing_entry_uses_fallback_title() -> None:
    result = _provider()._assemble([("9ZZZ", 0.5)], {}, 3, limit=10)
    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "PDB entry 9ZZZ"
    assert r.url == "https://www.rcsb.org/structure/9ZZZ"
    assert r.snippet == ""
    assert r.published_date is None


def test_assemble_respects_limit() -> None:
    hits = RcsbPdbProvider._parse_search(_SEARCH_RESPONSE)
    result = _provider()._assemble(hits, _GRAPHQL_RESPONSE, 9171, limit=1)
    assert len(result.results) == 1
    assert result.results[0].extra["pdb_id"] == "4HHB"


@pytest.mark.asyncio
async def test_search_hits_both_endpoints(respx_mock) -> None:
    import respx

    search_route = respx_mock.post(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE),
    )
    graph_route = respx_mock.post(_GRAPHQL_URL).mock(
        return_value=respx.MockResponse(200, json=_GRAPHQL_RESPONSE),
    )

    result = await _provider().search("hemoglobin", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "rcsb_pdb"
    assert search_route.called
    assert graph_route.called
    assert search_route.calls[0].request.content is not None
    search_body = search_route.calls[0].request.read().decode()
    assert '"full_text"' in search_body
    assert '"rows":5' in search_body
    graph_body = graph_route.calls[0].request.read().decode()
    assert '"ids":["4HHB","2PGH"]' in graph_body


@pytest.mark.asyncio
async def test_search_no_content_returns_empty(respx_mock) -> None:
    import respx

    respx_mock.post(_SEARCH_URL).mock(return_value=respx.MockResponse(204))
    graph_route = respx_mock.post(_GRAPHQL_URL).mock(
        return_value=respx.MockResponse(200, json=_GRAPHQL_RESPONSE),
    )

    result = await _provider().search("zzzzqqq", SearchParams(num_results=5))
    assert result.results == []
    assert not graph_route.called


@pytest.mark.asyncio
async def test_search_no_matches_skips_graphql(respx_mock) -> None:
    import respx

    respx_mock.post(_SEARCH_URL).mock(
        return_value=respx.MockResponse(
            200,
            json={"total_count": 0, "result_set": []},
        ),
    )
    graph_route = respx_mock.post(_GRAPHQL_URL).mock(
        return_value=respx.MockResponse(200, json=_GRAPHQL_RESPONSE),
    )

    result = await _provider().search("nothing", SearchParams(num_results=5))
    assert result.results == []
    assert not graph_route.called
