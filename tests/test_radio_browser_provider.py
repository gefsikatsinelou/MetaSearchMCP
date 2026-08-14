"""Unit tests for the Radio Browser radio station search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.radio_browser import RadioBrowserProvider

_SAMPLE_RESPONSE = [
    {
        "name": "SMOOTH JAZZ: Sax, piano, guitarra y voz: cool jazz",
        "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/ACIR22_s01AAC.aac",
        "url_resolved": (
            "https://playerservices.streamtheworld.com/api/livestream-redirect/ACIR22_s01AAC.aac"
        ),
        "homepage": "https://www.iheart.com/live/smooth-jazz-8063/",
        "favicon": "https://i.iheart.com/v3/re/assets.streams/63ee5ccb23c81aa16510435a",
        "tags": "jazz,cdmx,español,online",
        "country": "Mexico",
        "countrycode": "MX",
        "language": "spanish",
        "codec": "MP3",
        "bitrate": 128,
        "votes": 164,
        "state": "Mexico City",
    },
    {
        "name": "Classic FM",
        "url": "https://stream.example/classic.aac",
        "url_resolved": "https://stream.example/classic.aac",
        "homepage": "",
        "tags": "classical,uk",
        "country": "United Kingdom",
        "countrycode": "GB",
        "language": "english",
        "codec": "AAC",
        "bitrate": 192,
        "votes": 500,
    },
    {
        "name": "Broken Station",
        "url": "",
        "url_resolved": "",
        "homepage": "",
    },
]

_EMPTY_RESPONSE: list[dict[str, object]] = []


def _provider() -> RadioBrowserProvider:
    return RadioBrowserProvider()


def test_parse_basic():
    p = _provider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "SMOOTH JAZZ: Sax, piano, guitarra y voz: cool jazz"
    assert r.url == "https://www.iheart.com/live/smooth-jazz-8063/"
    assert "Country: Mexico" in r.snippet
    assert "Language: spanish" in r.snippet
    assert "Tags: jazz" in r.snippet
    assert "Stream: MP3 128 kbps" in r.snippet
    assert r.source == "radio-browser.info"
    assert r.provider == "radio_browser"
    assert r.rank == 1
    assert r.extra["stream_url"].startswith("https://playerservices.streamtheworld.com")
    assert r.extra["votes"] == 164
    assert r.extra["tags"] == ["jazz", "cdmx", "español", "online"]
    assert r.extra["country_code"] == "MX"


def test_parse_falls_back_to_stream_url():
    p = _provider()
    result = p._parse(_SAMPLE_RESPONSE)

    r = result.results[1]
    assert r.url == "https://stream.example/classic.aac"
    assert r.extra["homepage"] == ""


def test_parse_skips_station_without_url():
    p = _provider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    assert all(r.url for r in result.results)
    assert all(r.title for r in result.results)


def test_parse_empty():
    p = _provider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_parse_non_list():
    p = _provider()
    result = p._parse({"error": "not found"})
    assert result.results == []


def test_parse_ignores_non_dict_items():
    p = _provider()
    result = p._parse(["not-a-dict", None, 42])
    assert result.results == []


def test_stream_info():
    assert RadioBrowserProvider._stream_info("MP3", 128) == "MP3 128 kbps"
    assert RadioBrowserProvider._stream_info("AAC", None) == "AAC"
    assert RadioBrowserProvider._stream_info("", 0) == ""
    assert RadioBrowserProvider._stream_info("", None) == ""


def test_is_available():
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock):
    """The search method hits the Radio Browser endpoint and parses the response."""
    import respx

    respx_mock.get("https://all.api.radio-browser.info/json/stations/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("jazz", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "radio_browser"
    assert (
        result.results[0].title == "SMOOTH JAZZ: Sax, piano, guitarra y voz: cool jazz"
    )


@pytest.mark.asyncio
async def test_search_passes_query_params(respx_mock):
    """The search method forwards the query and filter parameters."""
    import respx

    route = respx_mock.get(
        "https://all.api.radio-browser.info/json/stations/search",
    ).mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    await p.search("classic fm", SearchParams(num_results=3))

    request = route.calls.last.request
    assert request.url.params["name"] == "classic fm"
    assert request.url.params["hidebroken"] == "true"
    assert request.url.params["order"] == "votes"
    assert request.url.params["reverse"] == "true"


@pytest.mark.asyncio
async def test_search_truncates_to_limit(respx_mock):
    """The search method truncates results to the requested limit."""
    import respx

    respx_mock.get("https://all.api.radio-browser.info/json/stations/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("jazz", SearchParams(num_results=1))

    assert len(result.results) == 1
    assert (
        result.results[0].title == "SMOOTH JAZZ: Sax, piano, guitarra y voz: cool jazz"
    )
