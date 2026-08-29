"""Unit tests for the Art Institute of Chicago collection search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.artic import ArticProvider

_SAMPLE_ITEM = {
    "id": 16568,
    "api_link": "https://api.artic.edu/api/v1/artworks/16568",
    "title": "Water Lilies",
    "artist_title": "Claude Monet",
    "date_display": "1906",
    "medium_display": "Oil on canvas",
    "department_title": "Painting and Sculpture of Europe",
    "image_id": "3c27b499-af56-f0d5-93b5-a7f2f1ad5813",
    "thumbnail": {
        "lqip": "data:image/gif;base64,R0lGODlh",
        "alt_text": "Painting of a pond with water lilies.",
    },
}

_SAMPLE_RESPONSE: dict[str, object] = {
    "pagination": {"total": 132681, "limit": 2, "offset": 0},
    "data": [
        _SAMPLE_ITEM,
        {
            "id": 16571,
            "api_link": "https://api.artic.edu/api/v1/artworks/16571",
            "title": "Arrival of the Normandy Train, Gare Saint-Lazare",
            "artist_title": "Claude Monet",
            "date_display": "1877",
            "medium_display": "Oil on canvas",
            "department_title": "Painting and Sculpture of Europe",
            "image_id": "0f1cc0e0-e42e-be16-3f71-2022da38cb93",
            "thumbnail": {"lqip": "data:image/gif;base64,R0lGODlh", "alt_text": ""},
        },
        {
            # Missing title -> skipped.
            "id": 99999,
            "api_link": "https://api.artic.edu/api/v1/artworks/99999",
            "artist_title": "Anonymous",
        },
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"pagination": {"total": 0}, "data": []}


def _provider() -> ArticProvider:
    return ArticProvider()


def test_artic_name_and_tags() -> None:
    p = _provider()
    assert p.name == "artic"
    assert p.tags == ["art", "image", "media"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Water Lilies"
    assert r.url == "https://api.artic.edu/api/v1/artworks/16568"
    assert "Claude Monet" in r.snippet
    assert "1906" in r.snippet
    assert "Painting and Sculpture of Europe" in r.snippet
    assert "Medium: Oil on canvas" in r.snippet
    assert r.provider == "artic"
    assert r.source == "artic.edu"
    assert r.rank == 1
    assert r.extra["artist"] == "Claude Monet"
    assert r.extra["date"] == "1906"
    assert r.extra["medium"] == "Oil on canvas"
    assert r.extra["department"] == "Painting and Sculpture of Europe"
    assert r.extra["image_id"] == "3c27b499-af56-f0d5-93b5-a7f2f1ad5813"
    assert r.extra["image_url"] == (
        "https://www.artic.edu/iiif/2/3c27b499-af56-f0d5-93b5-a7f2f1ad5813"
        "/full/843,/0/default.jpg"
    )
    assert r.extra["thumbnail_url"] == "data:image/gif;base64,R0lGODlh"
    assert r.extra["alt_text"] == "Painting of a pond with water lilies."


def test_parse_skips_items_missing_title() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert all(r.title for r in result.results)
    assert all(r.url for r in result.results)


def test_parse_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1
    assert result.results[0].title == "Water Lilies"


def test_parse_empty_and_malformed() -> None:
    assert _provider()._parse(_EMPTY_RESPONSE).results == []
    assert _provider()._parse({}).results == []
    assert _provider()._parse({"data": ["not-a-dict", None, 42]}).results == []
    assert _provider()._parse("junk").results == []


def test_image_url_handles_missing_and_slashed_ids() -> None:
    p = _provider()
    assert p._image_url(None) == ""
    assert p._image_url("") == ""
    assert p._image_url("/abc/def") == (
        "https://www.artic.edu/iiif/2/abc/def/full/843,/0/default.jpg"
    )


def test_clean_text() -> None:
    assert ArticProvider._clean("  a\n  b\t ") == "a b"
    assert ArticProvider._clean(None) == ""
    assert ArticProvider._clean("") == ""


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.artic.edu/api/v1/artworks/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("monet", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "artic"
    request = respx_mock.calls.last.request
    assert request.url.params["q"] == "monet"
    assert request.url.params["limit"] == "5"


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.artic.edu/api/v1/artworks/search").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("zzz", SearchParams(num_results=5))
    assert result.results == []
