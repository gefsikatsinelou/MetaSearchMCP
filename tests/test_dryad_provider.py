"""Unit tests for the Dryad research data repository provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.dryad import DryadProvider

_SEARCH_URL = "https://datadryad.org/api/v2/search"

_SAMPLE_DATASET: dict[str, object] = {
    "identifier": "doi:10.5061/dryad.8kprr4z23",
    "id": 175934,
    "storageSize": 2264137199,
    "relatedPublicationISSN": "1520-0442",
    "title": "Data from: Reduced evapotranspiration decreases land precipitation",
    "authors": [
        {"firstName": "Benjamin G", "lastName": "Buchovecky"},
        {"firstName": "F Hugo", "lastName": "Lambert"},
        {"firstName": "Claire M", "lastName": "Zarakas"},
        {"firstName": "Marysa M", "lastName": "Lague"},
    ],
    "abstract": "<p>Both canonical theory and <b>climate</b> models predict an "
    "increase in precipitation.</p>",
    "keywords": ["Climate modeling", "Land-atmosphere", "evapotranspiration"],
    "fieldOfScience": "Earth and related environmental sciences",
    "publicationDate": "2026-06-17",
    "versionNumber": 6,
    "versionStatus": "submitted",
    "curationStatus": "Published",
    "license": "https://spdx.org/licenses/CC0-1.0.html",
    "sharingLink": "http://datadryad.org/dataset/doi:10.5061/dryad.8kprr4z23",
    "metrics": {"views": 0, "downloads": 5, "citations": 1},
}

_SEARCH_RESPONSE: dict[str, object] = {
    "_links": {"self": {"href": "/api/v2/search?q=climate&per_page=5"}},
    "count": 1,
    "total": 702,
    "_embedded": {"stash:datasets": [_SAMPLE_DATASET]},
}

_EMPTY_RESPONSE: dict[str, object] = {
    "count": 0,
    "total": 0,
    "_embedded": {"stash:datasets": []},
}


def test_dryad_name_tags_and_availability():
    p = DryadProvider()
    assert p.name == "dryad"
    assert p.tags == ["academic", "data", "datasets", "repositories"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_dryad_parse_basic():
    p = DryadProvider()
    result = p._parse(_SEARCH_RESPONSE, limit=5)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title.startswith("Data from: Reduced evapotranspiration")
    assert r.url == "https://datadryad.org/dataset/doi:10.5061/dryad.8kprr4z23"
    assert r.source == "datadryad.org"
    assert r.provider == "dryad"
    assert r.rank == 1
    assert r.published_date == "2026-06-17"
    assert "Benjamin G Buchovecky" in r.snippet
    assert "et al." in r.snippet
    assert "Earth and related environmental sciences" in r.snippet
    assert "5 downloads" in r.snippet
    assert r.extra["doi"] == "doi:10.5061/dryad.8kprr4z23"
    assert r.extra["total_results"] == 702
    assert r.extra["authors"][0] == "Benjamin G Buchovecky"
    assert r.extra["keywords"] == [
        "Climate modeling",
        "Land-atmosphere",
        "evapotranspiration",
    ]
    assert r.extra["metrics"] == {"views": 0, "downloads": 5, "citations": 1}
    assert r.extra["version_number"] == 6
    assert r.extra["storage_size"] == 2264137199
    assert r.extra["related_publication_issn"] == "1520-0442"
    assert r.extra["download_url"] == (
        "https://datadryad.org/api/v2/datasets/doi%3A10.5061%2Fdryad.8kprr4z23/download"
    )


def test_dryad_abstract_is_html_stripped_and_truncated():
    p = DryadProvider()
    r = p._parse(_SEARCH_RESPONSE).results[0]
    assert r.extra["abstract"] == (
        "Both canonical theory and climate models predict an increase in precipitation."
    )
    long_abstract = "<p>" + ("word " * 400) + "</p>"
    payload = {
        "total": 1,
        "count": 1,
        "_embedded": {
            "stash:datasets": [{"title": "Long", "abstract": long_abstract}],
        },
    }
    assert len(p._parse(payload).results[0].extra["abstract"]) == 500


def test_dryad_parse_skips_records_without_title():
    payload = {
        "total": 2,
        "count": 2,
        "_embedded": {
            "stash:datasets": [
                {"identifier": "doi:1"},
                {"title": "Keep me", "identifier": "doi:2"},
            ],
        },
    }
    p = DryadProvider()
    results = p._parse(payload).results
    assert [r.title for r in results] == ["Keep me"]
    assert results[0].rank == 1


def test_dryad_parse_falls_back_to_sharing_link():
    """Records without an identifier fall back to the API sharing link."""
    payload = {
        "total": 1,
        "_embedded": {
            "stash:datasets": [
                {"title": "No id", "sharingLink": "http://datadryad.org/dataset/doi:3"},
            ],
        },
    }
    p = DryadProvider()
    r = p._parse(payload).results[0]
    assert r.url == "https://datadryad.org/dataset/doi:3"
    assert r.extra["download_url"] is None


def test_dryad_parse_respects_limit():
    payload = {
        "total": 3,
        "_embedded": {
            "stash:datasets": [
                {"title": "a"},
                {"title": "b"},
                {"title": "c"},
            ],
        },
    }
    p = DryadProvider()
    assert len(p._parse(payload, limit=2).results) == 2


def test_dryad_parse_empty_and_malformed():
    p = DryadProvider()
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []
    assert p._parse({"_embedded": "nope"}).results == []
    assert p._parse({"_embedded": {"stash:datasets": "nope"}}).results == []
    assert p._parse([1, 2, 3]).results == []
    assert p._parse(None).results == []


def test_dryad_parse_skips_non_dict_records_and_odd_fields():
    payload = {
        "total": 4,
        "_embedded": {
            "stash:datasets": [
                "not-a-dict",
                {"title": "  Spaced   title  ", "authors": "not-a-list"},
                {
                    "title": "Odd",
                    "authors": [{"firstName": "A"}, "nope", {}],
                    "metrics": {"views": True, "downloads": "many", "citations": 2},
                    "keywords": ["ok", 5, ""],
                },
            ],
        },
    }
    p = DryadProvider()
    results = p._parse(payload).results
    assert [r.title for r in results] == ["Spaced title", "Odd"]
    assert results[0].extra["doi"] == ""
    assert results[1].extra["authors"] == ["A"]
    assert results[1].extra["keywords"] == ["ok"]
    assert results[1].extra["metrics"] == {"citations": 2}
    # Non-integer metric values are dropped, so no download count appears.
    assert results[1].snippet == "A | ok"


def test_dryad_clean_and_text_helpers():
    from metasearchmcp.providers.dryad import _clean, _int, _strings, _text

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _text("<p>a &amp; b</p><br/>c") == "a & b c"
    assert _text(None) == ""
    assert _int(7) == 7
    assert _int(True) is None
    assert _int("7") is None
    assert _strings(["a", "", None]) == ["a"]
    assert _strings("nope") == []


@pytest.mark.asyncio
async def test_dryad_search_hits_api_and_parses(respx_mock):
    import respx

    route = respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE),
    )
    p = DryadProvider()
    result = await p.search("climate", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "dryad"
    request = route.calls.last.request
    assert request.url.params["q"] == "climate"
    assert request.url.params["per_page"] == "5"


@pytest.mark.asyncio
async def test_dryad_search_clamps_page_size_to_provider_max(respx_mock):
    """The page size never exceeds the configured per-provider maximum."""
    import respx

    route = respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )
    p = DryadProvider()
    await p.search("climate", SearchParams(num_results=50))

    assert route.calls.last.request.url.params["per_page"] == str(p._max_results)


@pytest.mark.asyncio
async def test_dryad_search_blank_query_makes_no_request(respx_mock):
    import respx

    route = respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )
    p = DryadProvider()
    result = await p.search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert route.call_count == 0


@pytest.mark.asyncio
async def test_dryad_search_raises_on_error_status(respx_mock):
    import httpx
    import respx

    respx_mock.get(_SEARCH_URL).mock(return_value=respx.MockResponse(503))
    p = DryadProvider()
    with pytest.raises(httpx.HTTPStatusError):
        await p.search("climate", SearchParams(num_results=5))


def test_dryad_is_registered():
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "dryad" in registry
    assert registry["dryad"].tags == ["academic", "data", "datasets", "repositories"]
