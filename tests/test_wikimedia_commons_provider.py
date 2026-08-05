"""Unit tests for the Wikimedia Commons image search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.providers.wikimedia_commons import WikimediaCommonsProvider


def _commons_response() -> dict:
    """Sample MediaWiki generator=search + imageinfo API response."""
    return {
        "query": {
            "pages": {
                "100": {
                    "pageid": 100,
                    "ns": 6,
                    "index": 1,
                    "title": "File:Mountain lake at sunset.jpg",
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/.../Mountain_lake.jpg",
                            "descriptionurl": (
                                "https://commons.wikimedia.org/wiki/"
                                "File:Mountain_lake_at_sunset.jpg"
                            ),
                            "thumburl": (
                                "https://upload.wikimedia.org/.../400px-"
                                "Mountain_lake.jpg?utm_source=commons.wikimedia.org"
                            ),
                            "width": 4000,
                            "height": 3000,
                            "extmetadata": {
                                "LicenseShortName": {
                                    "value": "CC BY-SA 4.0",
                                },
                                "Artist": {
                                    "value": (
                                        '<a href="//commons.wikimedia.org/wiki/'
                                        'User:Alice" title="User:Alice">Alice</a>'
                                    ),
                                },
                                "DateTimeOriginal": {
                                    "value": "2024-06-15 08:30:00",
                                },
                            },
                        },
                    ],
                },
                "101": {
                    "pageid": 101,
                    "ns": 6,
                    "index": 2,
                    "title": "File:River valley panorama.png",
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/.../River.png",
                            "descriptionurl": (
                                "https://commons.wikimedia.org/wiki/"
                                "File:River_valley_panorama.png"
                            ),
                            "thumburl": "https://upload.wikimedia.org/.../400px-River.png",
                            "width": 8000,
                            "height": 2000,
                            "extmetadata": {},
                        },
                    ],
                },
                "102": {
                    "pageid": 102,
                    "ns": 6,
                    "index": 3,
                    # Missing imageinfo -> should be skipped.
                    "title": "File:Broken entry.jpg",
                },
            },
        },
    }


def test_wikimedia_commons_parse_basic():
    p = WikimediaCommonsProvider()
    result = p._parse(_commons_response())

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Mountain lake at sunset.jpg"
    assert (
        r.url == "https://commons.wikimedia.org/wiki/File:Mountain_lake_at_sunset.jpg"
    )
    assert "4000x3000px" in r.snippet
    assert "License: CC BY-SA 4.0" in r.snippet
    assert "Author: Alice" in r.snippet
    assert r.provider == "wikimedia_commons"
    assert r.source == "commons.wikimedia.org"
    assert r.rank == 1
    assert r.published_date == "2024-06-15"


def test_wikimedia_commons_parse_extra_metadata():
    p = WikimediaCommonsProvider()
    result = p._parse(_commons_response())
    extra = result.results[0].extra

    assert extra["width"] == 4000
    assert extra["height"] == 3000
    assert extra["license"] == "CC BY-SA 4.0"
    assert extra["author"] == "Alice"
    # UTM tracking params are stripped from the thumbnail URL.
    assert "utm_source" not in extra["thumbnail_url"]
    assert extra["thumbnail_url"].startswith("https://upload.wikimedia.org/")
    assert extra["image_url"].startswith("https://upload.wikimedia.org/")


def test_wikimedia_commons_parse_empty_metadata():
    p = WikimediaCommonsProvider()
    result = p._parse(_commons_response())
    r = result.results[1]

    assert r.title == "River valley panorama.png"
    assert r.published_date is None
    assert r.extra["license"] == ""
    assert r.extra["author"] == ""


def test_wikimedia_commons_parse_skips_missing_imageinfo():
    p = WikimediaCommonsProvider()
    result = p._parse(_commons_response())
    titles = [r.title for r in result.results]
    assert "Broken entry.jpg" not in titles


def test_wikimedia_commons_parse_ranks():
    p = WikimediaCommonsProvider()
    result = p._parse(_commons_response())
    assert result.results[0].rank == 1
    assert result.results[1].rank == 2


def test_wikimedia_commons_parse_empty():
    p = WikimediaCommonsProvider()
    assert p._parse({}).results == []
    assert p._parse({"query": {"pages": {}}}).results == []


def test_wikimedia_commons_clean_metadata():
    assert WikimediaCommonsProvider._clean_metadata(None) == ""
    assert WikimediaCommonsProvider._clean_metadata("") == ""
    assert (
        WikimediaCommonsProvider._clean_metadata('<a href="/u">Bob</a> Smith')
        == "Bob Smith"
    )
    assert (
        WikimediaCommonsProvider._clean_metadata("  spaced\n text  ") == "spaced text"
    )


@pytest.mark.asyncio
async def test_wikimedia_commons_search_builds_query(respx_mock):
    """The search method sends a generator=search request and parses it."""
    import respx

    respx_mock.get("https://commons.wikimedia.org/w/api.php").mock(
        return_value=respx.MockResponse(200, json=_commons_response()),
    )

    from metasearchmcp.contracts import SearchParams

    p = WikimediaCommonsProvider()
    result = await p.search("mountain lake", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "wikimedia_commons"
