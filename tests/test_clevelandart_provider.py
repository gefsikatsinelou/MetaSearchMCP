"""Unit tests for the Cleveland Museum of Art collection search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.clevelandart import ClevelandArtProvider

_SAMPLE_ARTWORK = {
    "id": 135382,
    "accession_number": "1958.39",
    "title": "The Red Kerchief",
    "creation_date": "c. 1868\u201373",
    "technique": "oil on fabric",
    "department": "Modern European Painting and Sculpture",
    "type": "Painting",
    "url": "https://clevelandart.org/art/1958.39",
    "creditline": "Bequest of Leonard C. Hanna Jr.",
    "creators": [
        {
            "id": 1844,
            "description": "Claude Monet (French, 1840\u20131926)",
            "role": "artist",
        },
    ],
    "images": {
        "web": {
            "url": "https://openaccess-cdn.clevelandart.org/1958.39/1958.39_web.jpg",
            "width": "723",
            "height": "900",
        },
        "print": {
            "url": "https://openaccess-cdn.clevelandart.org/1958.39/1958.39_print.jpg",
        },
    },
}

_SEARCH_RESPONSE: dict[str, object] = {
    "info": {"total": 28},
    "data": [_SAMPLE_ARTWORK],
}

_EMPTY_SEARCH: dict[str, object] = {"info": {"total": 0}, "data": []}


def test_clevelandart_name_and_tags():
    p = ClevelandArtProvider()
    assert p.name == "clevelandart"
    assert p.tags == ["art", "images", "media"]


def test_clevelandart_parse_basic():
    p = ClevelandArtProvider()
    result = p._parse(_SEARCH_RESPONSE, limit=5)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "The Red Kerchief"
    assert r.url == "https://clevelandart.org/art/1958.39"
    assert r.provider == "clevelandart"
    assert r.rank == 1
    assert "Claude Monet" in r.snippet
    assert "1868" in r.snippet
    assert "Modern European Painting" in r.snippet
    assert r.source == "clevelandart.org"
    assert r.extra["artist"] == "Claude Monet (French, 1840\u20131926)"
    assert r.extra["accession_number"] == "1958.39"
    assert r.extra["creditline"] == "Bequest of Leonard C. Hanna Jr."
    assert r.extra["image_url"] == (
        "https://openaccess-cdn.clevelandart.org/1958.39/1958.39_web.jpg"
    )


def test_clevelandart_parse_skips_artwork_without_image():
    """Artworks without any usable image are skipped."""
    payload = {"info": {"total": 1}, "data": [{"id": 1, "title": "No image"}]}
    p = ClevelandArtProvider()
    assert p._parse(payload).results == []


def test_clevelandart_parse_empty_and_malformed():
    p = ClevelandArtProvider()
    assert p._parse(_EMPTY_SEARCH).results == []
    assert p._parse({"info": {}}).results == []
    assert p._parse(None).results == []
    assert p._parse([1, 2, 3]).results == []


def test_clevelandart_image_url_fallbacks():
    p = ClevelandArtProvider()
    # web image preferred
    assert p._image_url({"web": {"url": "w.jpg"}, "print": {"url": "p.jpg"}}) == "w.jpg"
    # falls back to print
    assert p._image_url({"print": {"url": "p.jpg"}}) == "p.jpg"
    assert p._image_url({"web": {"url": ""}}) == ""
    assert p._image_url(None) == ""
    assert p._image_url("not-a-dict") == ""


def test_clevelandart_clean():
    assert ClevelandArtProvider._clean("  a\n  b  ") == "a b"
    assert ClevelandArtProvider._clean(None) == ""
    assert ClevelandArtProvider._clean("") == ""


@pytest.mark.asyncio
async def test_clevelandart_search_hits_api_and_parses(respx_mock):
    """The search method hits the API and parses the response."""
    import respx

    respx_mock.get("https://openaccess-api.clevelandart.org/api/artworks/").mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE),
    )
    p = ClevelandArtProvider()
    result = await p.search("monet", SearchParams(num_results=5))

    assert len(result.results) == 1
    r = result.results[0]
    assert r.provider == "clevelandart"
    assert r.title == "The Red Kerchief"


@pytest.mark.asyncio
async def test_clevelandart_search_empty_response(respx_mock):
    """An empty data list yields no results."""
    import respx

    respx_mock.get("https://openaccess-api.clevelandart.org/api/artworks/").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_SEARCH),
    )
    p = ClevelandArtProvider()
    result = await p.search("zzz", SearchParams(num_results=5))
    assert result.results == []


@pytest.mark.asyncio
async def test_clevelandart_search_passes_query_param(respx_mock):
    """The search method forwards the query as the q parameter."""
    import respx

    route = respx_mock.get(
        "https://openaccess-api.clevelandart.org/api/artworks/"
    ).mock(return_value=respx.MockResponse(200, json=_EMPTY_SEARCH))
    p = ClevelandArtProvider()
    await p.search("van gogh", SearchParams(num_results=3))

    request = route.calls.last.request
    assert request.url.params["q"] == "van gogh"
    assert request.url.params["limit"] == "3"
