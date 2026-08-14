"""Unit tests for the TVMaze TV show search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.tvmaze import TVMazeProvider

_SAMPLE_RESPONSE = [
    {
        "score": 0.61280817,
        "show": {
            "id": 25376,
            "url": "https://www.tvmaze.com/shows/25376/python-hunters",
            "name": "Python Hunters",
            "type": "Reality",
            "language": "English",
            "genres": ["Nature"],
            "status": "Ended",
            "runtime": 60,
            "premiered": "2010-07-12",
            "officialSite": None,
            "summary": (
                "<p>They have no natural predators; they eat four times as much "
                "as an alligator. Now an elite squad of three licensed hunters "
                "is fighting back.</p>"
            ),
            "image": {
                "medium": "https://static.tvmaze.com/uploads/images/medium_portrait/363/909096.jpg",
                "original": "https://static.tvmaze.com/uploads/images/original_untouched/363/909096.jpg",
            },
            "network": {
                "id": 42,
                "name": "National Geographic",
                "country": {"name": "United States", "code": "US"},
            },
            "webChannel": None,
            "externals": {"tvrage": None, "thetvdb": 240321, "imdb": "tt1663677"},
            "rating": {"average": 7.5},
        },
    },
    {
        "score": 0.5,
        "show": {
            "id": 1,
            "url": "https://www.tvmaze.com/shows/1/under-the-dome",
            "name": "Under the Dome",
            "type": "Scripted",
            "language": "English",
            "genres": ["Drama", "Science-Fiction", "Thriller"],
            "status": "Ended",
            "runtime": 60,
            "premiered": "2013-06-24",
            "summary": "<p><b>Under the Dome</b> is the story of a small town.</p>",
            "image": {
                "medium": "https://static.tvmaze.com/uploads/images/medium_portrait/0/1.jpg"
            },
            "network": {"id": 2, "name": "CBS", "country": {"name": "United States"}},
            "webChannel": None,
            "externals": {"thetvdb": 264492, "imdb": "tt1553656"},
            "rating": {"average": 6.5},
        },
    },
    {
        "score": 0.4,
        "show": {
            "id": 2,
            "url": "",
            "name": "No URL Show",
            "type": "Scripted",
            "language": "English",
            "genres": [],
            "status": "",
            "premiered": None,
            "summary": "",
            "image": None,
            "network": None,
            "webChannel": {"id": 3, "name": "Netflix"},
            "externals": {},
            "rating": {},
        },
    },
]

_EMPTY_RESPONSE: list[dict[str, object]] = []


def test_tvmaze_parse_basic():
    p = TVMazeProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Python Hunters"
    assert r.url == "https://www.tvmaze.com/shows/25376/python-hunters"
    assert "elite squad" in r.snippet
    assert "Network: National Geographic" in r.snippet
    assert "Genres: Nature" in r.snippet
    assert r.source == "tvmaze.com"
    assert r.provider == "tvmaze"
    assert r.rank == 1
    assert r.published_date == "2010-07-12"
    assert (
        r.extra["thumbnail_url"]
        == "https://static.tvmaze.com/uploads/images/medium_portrait/363/909096.jpg"
    )
    assert r.extra["genres"] == ["Nature"]
    assert r.extra["status"] == "Ended"
    assert r.extra["network"] == "National Geographic"
    assert r.extra["premiered"] == "2010-07-12"
    assert r.extra["runtime"] == 60
    assert r.extra["rating"] == 7.5
    assert r.extra["tvdb_id"] == 240321
    assert r.extra["imdb_id"] == "tt1663677"
    assert r.extra["country"] == "United States"


def test_tvmaze_parse_ranks():
    p = TVMazeProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    assert result.results[0].rank == 1
    assert result.results[1].rank == 2


def test_tvmaze_parse_skips_show_without_url():
    p = TVMazeProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    assert len(result.results) == 2
    assert all(r.url for r in result.results)


def test_tvmaze_parse_empty():
    p = TVMazeProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_tvmaze_parse_non_list():
    p = TVMazeProvider()
    result = p._parse({"error": "not found"})
    assert result.results == []


def test_tvmaze_parse_missing_keys():
    p = TVMazeProvider()
    result = p._parse(
        [{"show": {"name": "Bare", "url": "https://www.tvmaze.com/shows/99/bare"}}]
    )
    r = result.results[0]
    assert r.title == "Bare"
    assert r.url == "https://www.tvmaze.com/shows/99/bare"
    assert r.snippet == ""
    assert r.published_date is None
    assert r.extra["genres"] == []
    assert r.extra["network"] == ""
    assert r.extra["rating"] is None


def test_tvmaze_parse_title_falls_back_to_url():
    p = TVMazeProvider()
    result = p._parse([{"show": {"url": "https://www.tvmaze.com/shows/99/nameless"}}])
    assert len(result.results) == 1
    assert result.results[0].title == "https://www.tvmaze.com/shows/99/nameless"


def test_tvmaze_webchannel_network():
    p = TVMazeProvider()
    result = p._parse(
        [
            {
                "show": {
                    "name": "Streamer Only",
                    "url": "https://www.tvmaze.com/shows/9/streamer-only",
                    "network": None,
                    "webChannel": {"name": "Netflix"},
                },
            },
        ],
    )
    assert result.results[0].extra["network"] == "Netflix"


def test_tvmaze_clean_summary():
    html = "<p><b>Hello</b> world<br /> line two</p>"
    assert TVMazeProvider._clean_summary(html) == "Hello world line two"
    assert TVMazeProvider._clean_summary("") == ""
    assert TVMazeProvider._clean_summary(None) == ""


def test_tvmaze_is_available():
    """Keyless provider is always available."""
    assert TVMazeProvider().is_available() is True


@pytest.mark.asyncio
async def test_tvmaze_search_hits_api_and_parses(respx_mock):
    """The search method hits the TVMaze endpoint and parses the response."""
    import respx

    respx_mock.get("https://api.tvmaze.com/search/shows").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = TVMazeProvider()
    result = await p.search("python", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "tvmaze"
    assert result.results[0].title == "Python Hunters"


@pytest.mark.asyncio
async def test_tvmaze_search_truncates_to_limit(respx_mock):
    """The search method truncates results to the requested limit."""
    import respx

    respx_mock.get("https://api.tvmaze.com/search/shows").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = TVMazeProvider()
    result = await p.search("python", SearchParams(num_results=1))

    assert len(result.results) == 1
    assert result.results[0].title == "Python Hunters"


@pytest.mark.asyncio
async def test_tvmaze_search_passes_query_param(respx_mock):
    """The search method forwards the query as the q parameter."""
    import respx

    route = respx_mock.get("https://api.tvmaze.com/search/shows").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = TVMazeProvider()
    await p.search("monty python", SearchParams(num_results=3))

    request = route.calls.last.request
    assert request.url.params["q"] == "monty python"
