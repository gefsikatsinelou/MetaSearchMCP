"""Unit tests for the Discogs music database search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.providers.discogs import DiscogsProvider

_SAMPLE_RESPONSE = {
    "pagination": {"page": 1, "per_page": 3, "items": 2},
    "results": [
        {
            "id": 4723572,
            "title": "Daft Punk - Get Lucky (Daft Punk Remix)",
            "uri": "/release/4723572-Daft-Punk-Get-Lucky-Daft-Punk-Remix",
            "country": "Europe",
            "year": "2013",
            "format": ["Vinyl", '12"', "33 ⅓ RPM"],
            "label": ["Columbia", "Sony Music"],
            "genre": ["Electronic", "Funk / Soul"],
            "style": ["Disco", "Funk", "Electro"],
            "type": "release",
            "cover_image": "https://img.discogs.com/cover.jpg",
            "thumb": "https://img.discogs.com/thumb.jpg",
        },
        {
            "id": 1234,
            "title": "Missing URI",
            "uri": "",
            "year": "2000",
            "type": "release",
        },
        {
            "id": 5678,
            "title": "",
            "uri": "/release/5678",
            "year": "1999",
            "type": "release",
        },
    ],
}

_EMPTY_RESPONSE = {"pagination": {"items": 0}, "results": []}


def test_discogs_parse_basic():
    p = DiscogsProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Daft Punk - Get Lucky (Daft Punk Remix)"
    assert (
        r.url
        == "https://www.discogs.com/release/4723572-Daft-Punk-Get-Lucky-Daft-Punk-Remix"
    )
    assert "Year: 2013" in r.snippet
    assert "Genre: Electronic, Funk / Soul" in r.snippet
    assert "Style: Disco, Funk, Electro" in r.snippet
    assert "Label: Columbia, Sony Music" in r.snippet
    assert "Format: Vinyl" in r.snippet
    assert r.source == "discogs.com"
    assert r.provider == "discogs"
    assert r.rank == 1
    assert r.published_date == "2013"
    assert r.extra["type"] == "release"
    assert r.extra["year"] == "2013"
    assert r.extra["genres"] == ["Electronic", "Funk / Soul"]
    assert r.extra["styles"] == ["Disco", "Funk", "Electro"]
    assert r.extra["image_url"] == "https://img.discogs.com/cover.jpg"


def test_discogs_parse_skips_missing_url_or_title():
    p = DiscogsProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    assert all(r.url for r in result.results)
    assert all(r.title for r in result.results)


def test_discogs_parse_empty():
    p = DiscogsProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_discogs_parse_sparse_item():
    p = DiscogsProvider()
    result = p._parse(
        {
            "results": [
                {
                    "title": "Only Title",
                    "uri": "/release/1",
                    "type": "release",
                }
            ]
        }
    )
    r = result.results[0]
    assert r.snippet == ""
    assert r.published_date is None
    assert r.extra["year"] == ""
    assert "image_url" not in r.extra


def test_discogs_join():
    assert DiscogsProvider._join(None) == []
    assert DiscogsProvider._join("not-a-list") == []
    assert DiscogsProvider._join([" a ", "", "b"]) == ["a", "b"]
    assert DiscogsProvider._join([str(i) for i in range(10)], max_items=2) == ["0", "1"]


def test_discogs_cover_url():
    item = {"cover_image": "c.jpg", "thumb": "t.jpg"}
    assert DiscogsProvider._cover_url(item) == "c.jpg"
    item = {"cover_image": "", "thumb": "t.jpg"}
    assert DiscogsProvider._cover_url(item) == "t.jpg"
    assert DiscogsProvider._cover_url({}) == ""


def test_discogs_is_available():
    """Keyless provider is always available."""
    assert DiscogsProvider().is_available() is True


@pytest.mark.asyncio
async def test_discogs_search_builds_query(respx_mock):
    """The search method hits the database endpoint and parses the response."""
    import respx

    respx_mock.get("https://api.discogs.com/database/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    from metasearchmcp.contracts import SearchParams

    p = DiscogsProvider()
    result = await p.search("daft punk", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "discogs"
