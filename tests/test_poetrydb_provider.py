"""Unit tests for the PoetryDB poetry provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.poetrydb import PoetryDbProvider

_TITLE_URL = "https://poetrydb.org/title/ozymandias"
_AUTHOR_URL = "https://poetrydb.org/author/ozymandias"
_LINES_URL = "https://poetrydb.org/lines/ozymandias"

_NOT_FOUND = {"status": 404, "reason": "Not found"}

_OZYMANDIAS = {
    "title": "Ozymandias",
    "author": "Percy Bysshe Shelley",
    "lines": [
        "I met a traveller from an antique land",
        "Who said: Two vast and trunkless legs of stone",
        "Stand in the desert...Near them, on the sand,",
        "Half sunk, a shattered visage lies, whose frown,",
    ],
    "linecount": "14",
}


def _mock(respx_mock, *, title=None, author=None, lines=None):
    """Mock the three PoetryDB field URLs; unmocked fields return "not found"."""
    routes = {}
    for field, url, payload in (
        ("title", _TITLE_URL, title),
        ("author", _AUTHOR_URL, author),
        ("lines", _LINES_URL, lines),
    ):
        body = _NOT_FOUND if payload is None else payload
        routes[field] = respx_mock.get(url).mock(
            return_value=respx.MockResponse(200, json=body),
        )
    return routes


def _provider() -> PoetryDbProvider:
    """Return a fresh provider instance for each test."""
    return PoetryDbProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "poetrydb"
    assert p.tags == ["books", "media", "reference"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "poetrydb" in registry
    assert registry["poetrydb"].tags == ["books", "media", "reference"]


@pytest.mark.asyncio
async def test_search_builds_result_from_title_match(respx_mock) -> None:
    _mock(respx_mock, title=[_OZYMANDIAS])

    result = await _provider().search("ozymandias", SearchParams(num_results=10))
    poem = result.results[0]

    assert poem.title == "Ozymandias"
    assert poem.url == "https://poetrydb.org/title/Ozymandias"
    assert poem.source == "poetrydb.org"
    assert poem.provider == "poetrydb"
    assert poem.rank == 1
    assert poem.published_date is None
    assert poem.snippet == (
        "Percy Bysshe Shelley | 14 lines | "
        "I met a traveller from an antique land | "
        "Who said: Two vast and trunkless legs of stone"
    )
    assert poem.extra == {
        "author": "Percy Bysshe Shelley",
        "linecount": 14,
        "lines": _OZYMANDIAS["lines"],
        "truncated": False,
    }


@pytest.mark.asyncio
async def test_search_falls_back_to_author_field(respx_mock) -> None:
    _mock(respx_mock, author=[_OZYMANDIAS])

    result = await _provider().search("ozymandias", SearchParams(num_results=10))

    assert [r.title for r in result.results] == ["Ozymandias"]
    assert result.results[0].extra["author"] == "Percy Bysshe Shelley"


@pytest.mark.asyncio
async def test_search_falls_back_to_lines_full_text(respx_mock) -> None:
    _mock(respx_mock, lines=[_OZYMANDIAS])

    result = await _provider().search("ozymandias", SearchParams(num_results=10))

    assert [r.title for r in result.results] == ["Ozymandias"]


@pytest.mark.asyncio
async def test_search_deduplicates_across_fields(respx_mock) -> None:
    # The same poem surfaces from all three fields and must appear once.
    _mock(
        respx_mock,
        title=[dict(_OZYMANDIAS)],
        author=[dict(_OZYMANDIAS)],
        lines=[dict(_OZYMANDIAS)],
    )

    result = await _provider().search("ozymandias", SearchParams(num_results=10))

    assert [r.title for r in result.results] == ["Ozymandias"]
    assert result.results[0].rank == 1


@pytest.mark.asyncio
async def test_search_respects_limit_and_stops_early(respx_mock) -> None:
    poems = [
        {"title": "Poem A", "author": "Author", "lines": ["a"], "linecount": "1"},
        {"title": "Poem B", "author": "Author", "lines": ["b"], "linecount": "1"},
        {"title": "Poem C", "author": "Author", "lines": ["c"], "linecount": "1"},
    ]
    routes = _mock(respx_mock, title=poems, author=poems, lines=poems)

    result = await _provider().search("ozymandias", SearchParams(num_results=1))

    assert [r.title for r in result.results] == ["Poem A"]
    # The limit is reached within the first field, so no further requests run.
    assert routes["title"].called
    assert not routes["author"].called
    assert not routes["lines"].called


@pytest.mark.asyncio
async def test_search_skips_entries_without_title(respx_mock) -> None:
    _mock(
        respx_mock,
        title=[{"author": "Anonymous", "lines": ["x"], "linecount": "1"}],
    )

    result = await _provider().search("ozymandias", SearchParams(num_results=10))

    assert result.results == []


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    routes = _mock(respx_mock, title=[_OZYMANDIAS])

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not routes["title"].called


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        "not a list",
        {"status": 404, "reason": "Not found"},
        [None, "x", 3, {"lines": ["x"]}],
        [],
    ],
)
async def test_search_handles_unexpected_payload_shapes(respx_mock, payload) -> None:
    routes = _mock(respx_mock, title=payload)
    result = await _provider().search("ozymandias", SearchParams(num_results=5))
    assert result.results == []
    assert routes["title"].called


@pytest.mark.asyncio
async def test_search_url_encodes_query(respx_mock) -> None:
    from urllib.parse import quote

    encoded = quote("the raven", safe="")
    title_route = respx_mock.get(f"https://poetrydb.org/title/{encoded}").mock(
        return_value=respx.MockResponse(200, json=[_OZYMANDIAS]),
    )
    respx_mock.get(f"https://poetrydb.org/author/{encoded}").mock(
        return_value=respx.MockResponse(200, json=_NOT_FOUND),
    )
    respx_mock.get(f"https://poetrydb.org/lines/{encoded}").mock(
        return_value=respx.MockResponse(200, json=_NOT_FOUND),
    )

    result = await _provider().search("the raven", SearchParams(num_results=5))

    assert title_route.called
    assert [r.title for r in result.results] == ["Ozymandias"]


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_TITLE_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("ozymandias", SearchParams(num_results=5))


def test_linecount_falls_back_to_lines_and_truncates() -> None:
    p = _provider()
    long_poem = {
        "title": "Long",
        "author": "Anonymous",
        "lines": [f"line {i}" for i in range(50)],
        # No linecount field: it must be derived from the lines.
    }

    built = p._build_result(long_poem, rank=1)

    assert built is not None
    assert built.extra["linecount"] == 50
    assert len(built.extra["lines"]) == 40
    assert built.extra["truncated"] is True


def test_build_result_returns_none_without_title() -> None:
    assert _provider()._build_result({"author": "x"}, rank=1) is None
