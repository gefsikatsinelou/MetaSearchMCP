"""Unit tests for the KEGG gene/pathway/disease/drug/compound search provider."""

from __future__ import annotations

from urllib.parse import quote

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.kegg import KeggProvider

_FIND_URL = "https://rest.kegg.jp/find/"
_ENTRY_PREFIX = "https://www.kegg.jp/entry/"
_DATABASES = ("genes", "pathway", "disease", "drug", "compound")

_TEXT = {
    "genes": (
        "hsa:10022\tINSL5, PRO182; insulin-like peptide INSL5 precursor\n"
        "hsa:3645\tINSRR, IRR; insulin receptor-related protein precursor\n"
    ),
    "pathway": "map04910\tInsulin signaling pathway\n",
    "disease": "H01228\tInsulin-resistant diabetes mellitus\n",
    "drug": "D00085\tInsulin (JAN/USP)\n",
    "compound": "C00723\tInsulin\n",
}


def _mock(respx_mock, query: str = "insulin", texts: dict[str, str] | None = None):
    """Mock every KEGG database endpoint for *query* and return the routes."""
    texts = _TEXT if texts is None else texts
    routes: dict[str, respx.Route] = {}
    for database in _DATABASES:
        url = f"{_FIND_URL}{database}/{quote(query, safe='')}"
        routes[database] = respx_mock.get(url).mock(
            return_value=respx.MockResponse(200, text=texts.get(database, "")),
        )
    return routes


def _provider() -> KeggProvider:
    """Return a fresh provider instance for each test."""
    return KeggProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "kegg"
    assert p.tags == ["academic", "web", "bio", "science"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "kegg" in registry
    assert registry["kegg"].tags == ["academic", "web", "bio", "science"]


@pytest.mark.asyncio
async def test_search_builds_structured_result(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("insulin", SearchParams(num_results=10))

    first = result.results[0]
    assert first.title == "INSL5, PRO182; insulin-like peptide INSL5 precursor"
    assert first.url == f"{_ENTRY_PREFIX}hsa:10022"
    assert first.source == "kegg.jp"
    assert first.provider == "kegg"
    assert first.rank == 1
    assert first.snippet == "INSL5, PRO182; insulin-like peptide INSL5 precursor"
    assert first.extra == {
        "entry_id": "hsa:10022",
        "database": "genes",
        "description": "INSL5, PRO182; insulin-like peptide INSL5 precursor",
    }

    # Round-robin merge: pathway/disease/drug/compound each contribute a hit
    # before the second genes hit is emitted.
    assert [r.title for r in result.results] == [
        "INSL5, PRO182; insulin-like peptide INSL5 precursor",
        "Insulin signaling pathway",
        "Insulin-resistant diabetes mellitus",
        "Insulin (JAN/USP)",
        "Insulin",
        "INSRR, IRR; insulin receptor-related protein precursor",
    ]
    assert [r.rank for r in result.results] == [1, 2, 3, 4, 5, 6]
    assert result.results[1].extra["database"] == "pathway"
    assert result.results[4].extra["database"] == "compound"


@pytest.mark.asyncio
async def test_search_skips_lines_without_description(respx_mock) -> None:
    _mock(
        respx_mock,
        texts={
            "genes": "hsa:1\tGood entry\nhsa:2\nnot-a-tabbed-line\n\n",
            "pathway": "",
            "disease": "",
            "drug": "",
            "compound": "",
        },
    )

    result = await _provider().search("insulin", SearchParams(num_results=10))

    assert [r.title for r in result.results] == ["Good entry"]


@pytest.mark.asyncio
async def test_search_deduplicates_entry_ids(respx_mock) -> None:
    _mock(
        respx_mock,
        texts={
            "genes": "hsa:1\tSame entry\nhsa:1\tSame entry\n",
            "pathway": "",
            "disease": "",
            "drug": "",
            "compound": "",
        },
    )

    result = await _provider().search("insulin", SearchParams(num_results=10))

    assert [r.title for r in result.results] == ["Same entry"]


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("insulin", SearchParams(num_results=2))

    assert [r.title for r in result.results] == [
        "INSL5, PRO182; insulin-like peptide INSL5 precursor",
        "Insulin signaling pathway",
    ]
    assert [r.rank for r in result.results] == [1, 2]


@pytest.mark.asyncio
async def test_search_skips_failing_database(respx_mock) -> None:
    routes = _mock(respx_mock)
    routes["genes"].mock(return_value=respx.MockResponse(500))

    result = await _provider().search("insulin", SearchParams(num_results=10))

    # genes hits are dropped, the remaining databases still contribute.
    assert "hsa:10022" not in [r.extra["entry_id"] for r in result.results]
    assert {r.extra["database"] for r in result.results} == {
        "pathway",
        "disease",
        "drug",
        "compound",
    }


@pytest.mark.asyncio
async def test_search_sends_encoded_query(respx_mock) -> None:
    routes = _mock(respx_mock, query="tumor protein")

    await _provider().search("tumor protein", SearchParams(num_results=5))

    for database in _DATABASES:
        assert routes[database].called
        request = routes[database].calls.last.request
        assert request.url.raw_path.decode() == f"/find/{database}/tumor%20protein"
        assert request.url.params == httpx.QueryParams()


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    routes = _mock(respx_mock)

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not any(route.called for route in routes.values())


@pytest.mark.asyncio
async def test_search_handles_unexpected_payload_shapes(respx_mock) -> None:
    routes = _mock(respx_mock, texts=dict.fromkeys(_DATABASES, ""))

    result = await _provider().search("insulin", SearchParams(num_results=5))

    assert result.results == []
    assert all(route.called for route in routes.values())


@pytest.mark.asyncio
async def test_search_tolerates_all_databases_failing(respx_mock) -> None:
    routes = _mock(respx_mock)
    for route in routes.values():
        route.mock(return_value=respx.MockResponse(503))

    result = await _provider().search("insulin", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_search_tolerates_connection_errors(respx_mock) -> None:
    routes = _mock(respx_mock)
    routes["genes"].mock(side_effect=httpx.ConnectError("boom"))

    result = await _provider().search("insulin", SearchParams(num_results=10))

    assert result.results
    assert all(r.extra["database"] != "genes" for r in result.results)
