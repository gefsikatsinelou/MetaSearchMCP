"""Unit tests for the Met Museum collection search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.metmuseum import MetMuseumProvider

_SAMPLE_OBJECT = {
    "objectID": 437112,
    "title": "Bouquet of Sunflowers",
    "artistDisplayName": "Claude Monet",
    "objectDate": "1881",
    "medium": "Oil on canvas",
    "department": "European Paintings",
    "primaryImage": "https://images.metmuseum.org/CRD/images/ep/original/DT1867.jpg",
    "primaryImageSmall": "https://images.metmuseum.org/CRD/images/ep/original/DT1867.jpg",
}

_SEARCH_RESPONSE: dict[str, object] = {
    "total": 136,
    "objectIDs": [437112],
}

_EMPTY_SEARCH: dict[str, object] = {"total": 0, "objectIDs": []}


def test_metmuseum_name_and_tags():
    p = MetMuseumProvider()
    assert p.name == "metmuseum"
    assert p.tags == ["art", "images", "media"]


def test_metmuseum_parse_object_basic():
    p = MetMuseumProvider()
    result = p._parse_object(437112, _SAMPLE_OBJECT, rank=1)

    assert result is not None
    assert result.title == "Bouquet of Sunflowers"
    assert result.url == "https://www.metmuseum.org/art/collection/search/437112"
    assert "Claude Monet" in result.snippet
    assert "1881" in result.snippet
    assert "European Paintings" in result.snippet
    assert result.provider == "metmuseum"
    assert result.rank == 1
    assert result.extra["artist"] == "Claude Monet"
    assert result.extra["object_id"] == 437112
    assert result.extra["thumbnail_url"].startswith("https://")


def test_metmuseum_parse_object_missing_title():
    p = MetMuseumProvider()
    assert p._parse_object(1, {"artistDisplayName": "No title"}, rank=1) is None


def test_metmuseum_clean_text():
    assert MetMuseumProvider._clean_text("  a\n  b  ") == "a b"
    assert MetMuseumProvider._clean_text(None) == ""
    assert MetMuseumProvider._clean_text("") == ""


@pytest.mark.asyncio
async def test_metmuseum_fetch_object_no_image(respx_mock):
    """Objects without a primary image are skipped."""
    import respx

    respx_mock.get(
        "https://collectionapi.metmuseum.org/public/collection/v1/objects/7"
    ).mock(
        return_value=respx.MockResponse(200, json={"objectID": 7, "title": "No image"}),
    )
    p = MetMuseumProvider()
    assert await p._fetch_object(p._client(), 7) is None


@pytest.mark.asyncio
async def test_metmuseum_fetch_object_http_error(respx_mock):
    """An HTTP error fetching an object is swallowed (best-effort)."""
    import respx

    respx_mock.get(
        "https://collectionapi.metmuseum.org/public/collection/v1/objects/9"
    ).mock(
        return_value=respx.MockResponse(500),
    )
    p = MetMuseumProvider()
    assert await p._fetch_object(p._client(), 9) is None


@pytest.mark.asyncio
async def test_metmuseum_search_hits_api_and_parses(respx_mock):
    """The search method fetches the object list and then object details."""
    import respx

    respx_mock.get(
        "https://collectionapi.metmuseum.org/public/collection/v1/search"
    ).mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE),
    )
    respx_mock.get(
        "https://collectionapi.metmuseum.org/public/collection/v1/objects/437112"
    ).mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_OBJECT),
    )

    p = MetMuseumProvider()
    result = await p.search("sunflowers", SearchParams(num_results=5))

    assert len(result.results) == 1
    r = result.results[0]
    assert r.provider == "metmuseum"
    assert r.title == "Bouquet of Sunflowers"


@pytest.mark.asyncio
async def test_metmuseum_search_empty_response(respx_mock):
    """An empty object list yields no results."""
    import respx

    respx_mock.get(
        "https://collectionapi.metmuseum.org/public/collection/v1/search"
    ).mock(
        return_value=respx.MockResponse(200, json=_EMPTY_SEARCH),
    )
    p = MetMuseumProvider()
    result = await p.search("zzz", SearchParams(num_results=5))
    assert result.results == []


@pytest.mark.asyncio
async def test_metmuseum_search_passes_query_param(respx_mock):
    """The search method forwards the query as the q parameter."""
    import respx

    route = respx_mock.get(
        "https://collectionapi.metmuseum.org/public/collection/v1/search"
    ).mock(
        return_value=respx.MockResponse(200, json=_EMPTY_SEARCH),
    )
    p = MetMuseumProvider()
    await p.search("van gogh", SearchParams(num_results=3))

    request = route.calls.last.request
    assert request.url.params["q"] == "van gogh"
    assert request.url.params["hasImages"] == "true"
