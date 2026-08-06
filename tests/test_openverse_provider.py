"""Unit tests for the Openverse image search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.providers.openverse import OpenverseProvider

_SAMPLE_RESPONSE = {
    "result_count": 2,
    "results": [
        {
            "id": "img-1",
            "title": "Aurora over the mountains",
            "foreign_landing_url": "https://www.flickr.com/photos/123/456",
            "url": "https://live.staticflickr.com/1/aurora.jpg",
            "creator": "well_lucio",
            "creator_url": "https://www.flickr.com/photos/123",
            "license": "by-nd",
            "license_version": "2.0",
            "license_url": "https://creativecommons.org/licenses/by-nd/2.0/",
            "provider": "flickr",
            "source": "flickr",
            "indexed_on": "2020-05-03T05:48:27.285165Z",
            "thumbnail": "https://api.openverse.org/v1/images/img-1/thumb/",
            "mature": False,
            "width": 477,
            "height": 312,
        },
        {
            "id": "img-2",
            "title": "No URL Image",
            "url": "",
            "foreign_landing_url": "",
            "provider": "flickr",
        },
    ],
}

_EMPTY_RESPONSE = {"result_count": 0, "results": []}


def test_openverse_parse_basic():
    p = OpenverseProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Aurora over the mountains"
    assert r.url == "https://www.flickr.com/photos/123/456"
    assert "477x312px" in r.snippet
    assert "License: CC BY-ND 2.0" in r.snippet
    assert "Author: well_lucio" in r.snippet
    assert "Source: flickr" in r.snippet
    assert r.source == "openverse.org"
    assert r.provider == "openverse"
    assert r.rank == 1
    assert r.published_date == "2020-05-03"
    assert (
        r.extra["thumbnail_url"] == "https://api.openverse.org/v1/images/img-1/thumb/"
    )
    assert r.extra["image_url"] == "https://live.staticflickr.com/1/aurora.jpg"
    assert r.extra["landing_url"] == "https://www.flickr.com/photos/123/456"
    assert r.extra["width"] == 477
    assert r.extra["height"] == 312
    assert r.extra["license"] == "CC BY-ND 2.0"
    assert r.extra["author"] == "well_lucio"
    assert r.extra["source_provider"] == "flickr"
    assert r.extra["mature"] is False


def test_openverse_parse_skips_item_without_url():
    p = OpenverseProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    assert all(r.url for r in result.results)


def test_openverse_parse_empty():
    p = OpenverseProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_openverse_parse_missing_keys():
    p = OpenverseProvider()
    result = p._parse(
        {
            "results": [
                {
                    "title": "Lonely",
                    "url": "https://cdn.example/x.jpg",
                    "foreign_landing_url": "",
                },
            ],
        },
    )
    r = result.results[0]
    assert r.snippet == ""
    assert r.published_date is None
    assert r.extra["license"] == ""
    assert r.extra["author"] == ""
    assert r.extra["width"] is None


def test_openverse_license_label():
    assert OpenverseProvider._license_label("by", "4.0") == "CC BY 4.0"
    assert OpenverseProvider._license_label("by-nc", None) == "CC BY-NC"
    assert OpenverseProvider._license_label("", "2.0") == ""
    assert OpenverseProvider._license_label(None, None) == ""


def test_openverse_clean_text():
    assert OpenverseProvider._clean_text("  a\n  b ") == "a b"
    assert OpenverseProvider._clean_text("") == ""
    assert OpenverseProvider._clean_text(None) == ""


def test_openverse_is_available():
    """Keyless provider is always available."""
    assert OpenverseProvider().is_available() is True


@pytest.mark.asyncio
async def test_openverse_search_builds_query(respx_mock):
    """The search method hits the images endpoint and parses the response."""
    import respx

    respx_mock.get("https://api.openverse.org/v1/images").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    from metasearchmcp.contracts import SearchParams

    p = OpenverseProvider()
    result = await p.search("aurora", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "openverse"
