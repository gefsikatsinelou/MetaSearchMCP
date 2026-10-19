"""Unit tests for the DBpedia Lookup entity search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.dbpedia import DBpediaProvider

_SAMPLE_RESPONSE: dict[str, object] = {
    "docs": [
        {
            "score": ["45709.703"],
            "refCount": ["4685"],
            "resource": ["http://dbpedia.org/resource/Berlin"],
            "typeName": ["Settlement", "City", "Place"],
            "comment": [
                "<B>Berlin</B> is the capital and largest city of Germany by "
                "both area and population."
            ],
            "label": ["<B>Berlin</B>"],
            "id": ["http://dbpedia.org/resource/Berlin"],
            "type": [
                "http://dbpedia.org/ontology/Settlement",
                "http://dbpedia.org/ontology/City",
            ],
            "category": [
                "http://dbpedia.org/resource/Category:Berlin",
                "http://dbpedia.org/resource/Category:City-states",
            ],
        },
        {
            # Sparse record: only a label, no resource -> derived URL.
            "label": ["Python &amp; Friends"],
            "type": ["http://dbpedia.org/ontology/ProgrammingLanguage"],
        },
        # Non-dict payload -> skipped.
        "junk",
        None,
        # No label/resource -> skipped.
        {"comment": ["orphan"]},
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"docs": []}


def _provider() -> DBpediaProvider:
    return DBpediaProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "dbpedia"
    assert p.tags == ["web", "academic", "knowledge", "reference"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert [r.title for r in result.results] == ["Berlin", "Python & Friends"]
    r = result.results[0]
    assert r.url == "http://dbpedia.org/resource/Berlin"
    assert r.provider == "dbpedia"
    assert r.source == "dbpedia.org"
    assert r.rank == 1
    assert r.published_date is None
    # Highlight markup is stripped and entities are unescaped.
    assert "<B>" not in r.snippet
    assert "Berlin is the capital" in r.snippet
    assert "types: Settlement, City, Place" in r.snippet
    assert r.extra["resource"] == "http://dbpedia.org/resource/Berlin"
    assert r.extra["types"] == ["Settlement", "City", "Place"]
    assert r.extra["categories"] == ["Berlin", "City-states"]
    assert r.extra["ref_count"] == "4685"
    assert r.extra["score"] == "45709.703"


def test_parse_sparse_record() -> None:
    r = _provider()._parse(_SAMPLE_RESPONSE).results[1]
    assert r.title == "Python & Friends"
    assert r.url == "https://dbpedia.org/page/Python_&_Friends"
    assert r.extra["types"] == ["ProgrammingLanguage"]
    assert r.extra["categories"] == []
    assert r.rank == 2


def test_parse_drops_malformed_entries() -> None:
    results = _provider()._parse(_SAMPLE_RESPONSE).results
    assert len(results) == 2
    assert "junk" not in {r.title for r in results}


def test_parse_empty_and_junk() -> None:
    p = _provider()
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []
    assert p._parse({"docs": "junk"}).results == []  # type: ignore[dict-item]
    assert p._parse([1, 2, 3]).results == []  # type: ignore[arg-type]
    assert p._parse(None).results == []  # type: ignore[arg-type]


def test_parse_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1
    assert result.results[0].extra["resource"] == "http://dbpedia.org/resource/Berlin"


def test_parse_snippet_capped_at_shared_limit() -> None:
    from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH

    long_comment = "x" * (MAX_SNIPPET_LENGTH + 200)
    result = _provider()._parse(
        {"docs": [{"label": ["Long"], "comment": [long_comment]}]},
    )
    assert len(result.results[0].snippet) == MAX_SNIPPET_LENGTH


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_query_params(respx_mock) -> None:
    import respx

    respx_mock.get("https://lookup.dbpedia.org/api/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("berlin", SearchParams(num_results=5))

    assert len(result.results) == 2
    request = respx_mock.calls.last.request
    assert request.url.params["query"] == "berlin"
    assert request.url.params["format"] == "JSON"
    assert request.url.params["maxResults"] == "5"


@pytest.mark.asyncio
async def test_search_empty_query_short_circuits(respx_mock) -> None:
    import respx

    route = respx_mock.get("https://lookup.dbpedia.org/api/search").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://lookup.dbpedia.org/api/search").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    result = await _provider().search("no-such-entity-xyz", SearchParams(num_results=5))
    assert result.results == []
