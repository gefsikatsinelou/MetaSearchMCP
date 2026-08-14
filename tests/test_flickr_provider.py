"""Unit tests for the Flickr public feed image search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.providers.flickr import FlickrProvider

_SAMPLE_RESPONSE = {
    "items": [
        {
            "title": "Lac d'Espingo",
            "link": "https://www.flickr.com/photos/dreamtimenaturephotography/55461908457/",
            "media": {
                "m": "https://live.staticflickr.com/65535/55461908457_d734a025d4_m.jpg",
            },
            "author": (
                'nobody@flickr.com ("Julien Rouard - Dreamtime Nature Photography")'
            ),
            "tags": "mountain lake france nature",
            "published": "2026-08-10T09:30:00Z",
            "date_taken": "2026-08-01T12:00:00-05:00",
            "description": (
                '<p><a href="https://www.flickr.com/people/'
                'dreamtimenaturephotography/">Julien Rouard</a> posted a photo:</p> '
                "<p>Lac d'Espingo<br /> Haute Garonne<br /> France</p>"
            ),
        },
        {
            "title": "No Link Photo",
            "link": "",
            "media": {"m": "https://live.staticflickr.com/1/none.jpg"},
            "author": 'nobody@flickr.com ("Unknown")',
            "tags": "",
            "description": "",
        },
    ],
}

_EMPTY_RESPONSE = {"items": []}


def test_flickr_parse_basic():
    p = FlickrProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Lac d'Espingo"
    assert (
        r.url == "https://www.flickr.com/photos/dreamtimenaturephotography/55461908457/"
    )
    assert "Julien Rouard" in r.snippet
    assert "Haute Garonne" in r.snippet
    assert r.source == "flickr.com"
    assert r.provider == "flickr"
    assert r.rank == 1
    assert r.published_date == "2026-08-10"
    assert (
        r.extra["thumbnail_url"]
        == "https://live.staticflickr.com/65535/55461908457_d734a025d4_m.jpg"
    )
    assert r.extra["author"] == "Julien Rouard - Dreamtime Nature Photography"
    assert r.extra["tags"] == ["mountain", "lake", "france", "nature"]
    assert r.extra["date_taken"] == "2026-08-01"


def test_flickr_parse_skips_item_without_link():
    p = FlickrProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    assert len(result.results) == 1
    assert all(r.url for r in result.results)


def test_flickr_parse_empty():
    p = FlickrProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_flickr_parse_missing_keys():
    p = FlickrProvider()
    result = p._parse(
        {
            "items": [
                {
                    "title": "Lonely",
                    "link": "https://flickr.com/photos/1/2",
                    "media": {},
                    "author": "",
                    "tags": "",
                    "description": "",
                },
            ],
        },
    )
    r = result.results[0]
    assert r.snippet == ""
    assert r.published_date is None
    assert r.extra["author"] == ""
    assert r.extra["tags"] == []
    assert r.extra["thumbnail_url"] == ""


def test_flickr_author_name():
    assert (
        FlickrProvider._author_name('nobody@flickr.com ("Alice Wonder")')
        == "Alice Wonder"
    )
    assert FlickrProvider._author_name("nobody@flickr.com") == ""
    assert FlickrProvider._author_name("") == ""
    assert FlickrProvider._author_name(None) == ""


def test_flickr_snippet_from_description():
    p = FlickrProvider()
    snippet = p._snippet_from_description(
        "<p><b>Hello</b> world<br /> second line</p>",
    )
    assert "Hello world" in snippet
    assert "second line" in snippet
    assert "<" not in snippet


def test_flickr_is_available():
    """Keyless provider is always available."""
    assert FlickrProvider().is_available() is True


@pytest.mark.asyncio
async def test_flickr_search_hits_feed_and_parses(respx_mock):
    """The search method hits the public feed and parses the response."""
    import respx

    respx_mock.get(
        "https://www.flickr.com/services/feeds/photos_public.gne",
    ).mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    from metasearchmcp.contracts import SearchParams

    p = FlickrProvider()
    result = await p.search("mountain", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "flickr"
    assert result.results[0].title == "Lac d'Espingo"
