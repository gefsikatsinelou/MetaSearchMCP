"""Unit tests for the NASA Image and Video Library search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.nasa import NasaProvider

_SAMPLE_ITEM = {
    "href": "https://images-assets.nasa.gov/image/NHQ201906010007/collection.json",
    "data": [
        {
            "center": "HQ",
            "date_created": "2019-06-01T00:00:00Z",
            "description": (
                "The Mars celebration Saturday, June 1, 2019, in Mars, "
                "Pennsylvania. Photo Credit: (NASA/Bill Ingalls)"
            ),
            "keywords": ["Mars", "Mars Celebration", "Pennsylvania"],
            "location": "Mars, PA, USA",
            "media_type": "image",
            "nasa_id": "NHQ201906010007",
            "photographer": "NASA/Bill Ingalls",
            "title": "Mars Celebration",
        },
    ],
    "links": [
        {
            "href": "https://images-assets.nasa.gov/image/NHQ201906010007/NHQ201906010007~medium.jpg",
            "rel": "alternate",
            "render": "image",
        },
        {
            "href": "https://images-assets.nasa.gov/image/NHQ201906010007/NHQ201906010007~thumb.jpg",
            "rel": "preview",
            "render": "image",
        },
    ],
}

# An item that appears in the "lite" result type: no links, video media type.
_SAMPLE_VIDEO_ITEM = {
    "href": "https://images-assets.nasa.gov/video/GSFC_00001234/collection.json",
    "data": [
        {
            "center": "GSFC",
            "date_created": "2020-02-20T10:00:00Z",
            "description": "A NASA video about Earth observations.",
            "keywords": ["Earth"],
            "media_type": "video",
            "nasa_id": "GSFC_00001234",
            "title": "Earth from Space",
        },
    ],
    "links": [
        {
            "href": "https://images-assets.nasa.gov/video/GSFC_00001234/GSFC_00001234~thumb.jpg",
            "rel": "preview",
        },
    ],
}

_SAMPLE_RESPONSE = {
    "collection": {
        "version": "1.1",
        "metadata": {"total_hits": 2},
        "items": [_SAMPLE_ITEM, _SAMPLE_VIDEO_ITEM],
    },
}

_EMPTY_RESPONSE = {
    "collection": {"version": "1.1", "metadata": {"total_hits": 0}, "items": []},
}


def test_nasa_parse_basic():
    p = NasaProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Mars Celebration"
    assert r.url == "https://images.nasa.gov/details/NHQ201906010007"
    assert "The Mars celebration" in r.snippet
    assert "Photographer: NASA/Bill Ingalls" in r.snippet
    assert "Location: Mars, PA, USA" in r.snippet
    assert r.source == "images.nasa.gov"
    assert r.provider == "nasa"
    assert r.rank == 1
    assert r.published_date == "2019-06-01"
    assert r.extra["nasa_id"] == "NHQ201906010007"
    assert r.extra["media_type"] == "image"
    assert r.extra["photographer"] == "NASA/Bill Ingalls"
    assert r.extra["location"] == "Mars, PA, USA"
    assert r.extra["keywords"] == ["Mars", "Mars Celebration", "Pennsylvania"]
    assert r.extra["center"] == "HQ"
    assert r.extra["preview_url"].endswith("~thumb.jpg")


def test_nasa_parse_video_item():
    p = NasaProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    video = result.results[1]
    assert video.extra["media_type"] == "video"
    assert "Media: video" in video.snippet
    assert video.published_date == "2020-02-20"
    assert video.extra["preview_url"].endswith("~thumb.jpg")


def test_nasa_parse_skips_item_without_nasa_id_or_title():
    p = NasaProvider()
    response = {
        "collection": {
            "items": [
                {"data": [{"title": "No id"}]},
                {"data": [{"nasa_id": "ABC1", "title": ""}]},
                {"data": []},
                {"data": ["not-a-dict"]},
                "not-a-dict",
            ],
        },
    }
    result = p._parse(response)
    assert result.results == []


def test_nasa_parse_url_encodes_nasa_id():
    p = NasaProvider()
    response = {
        "collection": {
            "items": [
                {
                    "data": [
                        {
                            "nasa_id": "NDTV ABC 123",
                            "title": "Apollo Digest: Spacecraft",
                            "description": "",
                        },
                    ],
                },
            ],
        },
    }
    result = p._parse(response)
    assert result.results[0].url == "https://images.nasa.gov/details/NDTV%20ABC%20123"


def test_nasa_parse_empty():
    p = NasaProvider()
    assert p._parse(_EMPTY_RESPONSE).results == []


def test_nasa_parse_non_dict_or_missing_collection():
    p = NasaProvider()
    assert p._parse(None).results == []
    assert p._parse([{"data": []}]).results == []
    assert p._parse({"collection": None}).results == []
    assert p._parse({"collection": {"items": None}}).results == []


def test_nasa_clean():
    assert NasaProvider._clean("  hello\n world  ") == "hello world"
    assert NasaProvider._clean("") == ""
    assert NasaProvider._clean(None) == ""


def test_nasa_preview_url_prefers_preview_link():
    item = {
        "links": [
            {"rel": "alternate", "href": "https://a.jpg"},
            {"rel": "preview", "href": "https://b.jpg"},
        ],
    }
    assert NasaProvider._preview_url(item) == "https://b.jpg"


def test_nasa_preview_url_falls_back_to_first_href():
    item = {
        "links": [
            {"rel": "alternate", "href": "https://a.jpg"},
            {"rel": "alternate", "href": "https://c.jpg"},
        ],
    }
    assert NasaProvider._preview_url(item) == "https://a.jpg"
    assert NasaProvider._preview_url({"links": []}) == ""
    assert NasaProvider._preview_url({}) == ""


def test_nasa_is_available():
    """Keyless provider is always available."""
    assert NasaProvider().is_available() is True


@pytest.mark.asyncio
async def test_nasa_search_hits_api_and_parses(respx_mock):
    """The search method hits the /search endpoint and parses the response."""
    import respx

    respx_mock.get("https://images-api.nasa.gov/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = NasaProvider()
    result = await p.search("mars", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "nasa"
    assert result.results[0].title == "Mars Celebration"


@pytest.mark.asyncio
async def test_nasa_search_empty_response(respx_mock):
    """An empty items list yields no results."""
    import respx

    respx_mock.get("https://images-api.nasa.gov/search").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = NasaProvider()
    result = await p.search("zzz", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_nasa_search_truncates_to_limit(respx_mock):
    """The search method truncates results to the requested limit."""
    import respx

    many_items = {
        "collection": {
            "items": [
                {
                    "data": [
                        {
                            "nasa_id": f"ID{i:04d}",
                            "title": f"Asset {i}",
                            "description": "",
                        },
                    ],
                }
                for i in range(1, 6)
            ],
        },
    }
    respx_mock.get("https://images-api.nasa.gov/search").mock(
        return_value=respx.MockResponse(200, json=many_items),
    )

    p = NasaProvider()
    result = await p.search("test", SearchParams(num_results=2))

    assert len(result.results) == 2
    assert result.results[0].title == "Asset 1"


@pytest.mark.asyncio
async def test_nasa_search_passes_query_param(respx_mock):
    """The search method forwards the query as the q parameter."""
    import respx

    route = respx_mock.get("https://images-api.nasa.gov/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = NasaProvider()
    await p.search("apollo 11", SearchParams(num_results=3))

    request = route.calls.last.request
    assert request.url.params["q"] == "apollo 11"
    assert request.url.params["media_type"] == "image,video"
    assert request.url.params["page_size"] == "3"
