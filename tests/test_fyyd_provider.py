"""Unit tests for the fyyd podcast episode search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.fyyd import FyydProvider

_EPISODE_URL = "https://api.fyyd.de/0.2/search/episode"
_PODCAST_URL = "https://api.fyyd.de/0.2/search/podcast"

_EPISODE_RESPONSE: dict[str, object] = {
    "status": 1,
    "msg": "ok",
    "meta": {"API_INFO": {"API_VERSION": "0.2"}},
    "data": [
        {
            "id": 16021018,
            "title": "LLMs are real, AI is fake",
            "guid": "https://craphound.com/?p=12733",
            "url": "https://craphound.com/news/2026/09/27/llms-are-real-ai-is-fake/",
            "enclosure": "https://example.org/audio/doctorow-524.mp3",
            "podcast_id": 1289,
            "imgURL": "https://img.fyyd.de/pd/layout/doctorow.jpg",
            "pubdate": "2026-09-28T01:48:52+02:00",
            "duration": None,
            "duration_string": "n/a",
            "status": 200,
            "num_season": 0,
            "num_episode": 0,
            "url_fyyd": "https://fyyd.de/episode/16021018",
            "content_type": "audio/mpeg",
            "description": "This week on my podcast, I read LLMs are real, AI is fake.",
        },
        {
            # No page URL: the fyyd episode page must be used instead, and the
            # integer duration must be rendered as h:mm:ss.
            "id": 16021019,
            "title": "pyinfra basics",
            "guid": "https://example.org/ep2",
            "url": "",
            "enclosure": "https://example.org/audio/ep2.mp3",
            "podcast_id": 42,
            "imgURL": "",
            "pubdate": "2026-09-27T14:30:00+02:00",
            "duration": 3605,
            "duration_string": "1:00:05",
            "num_season": 2,
            "num_episode": 7,
            "url_fyyd": "https://fyyd.de/episode/16021019",
            "content_type": "audio/mpeg",
            "description": "An episode about pyinfra.",
        },
        # Duplicate id of the first record — must be collapsed.
        {
            "id": 16021018,
            "title": "LLMs are real, AI is fake (duplicate)",
            "url": "https://example.org/duplicate",
        },
        "junk",
    ],
}

_PODCAST_RESPONSE: dict[str, object] = {
    "status": 1,
    "msg": "ok",
    "meta": {"API_INFO": {"API_VERSION": "0.2"}},
    "data": [
        {
            "id": 78641,
            "title": "The TWIML AI Podcast",
            "xmlURL": "https://feeds.megaphone.fm/MLN2155636147",
            "htmlURL": "https://twimlai.com",
            "imgURL": "https://megaphone.imgix.net/podcasts/twiml.jpg",
            "language": "en",
            "author": "Sam Charrington",
            "episode_count": 795,
            "categories": [203, 155],
            "lastpub": "2026-09-16T23:57:00+02:00",
            "rank": 280,
            "url_fyyd": "https://fyyd.de/podcast/the-twiml-ai-podcast/0",
            "description": "Machine learning and artificial intelligence interviews.",
        },
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {
    "status": 1,
    "msg": "ok",
    "meta": {"API_INFO": {"API_VERSION": "0.2"}},
    "data": [],
}


def _provider() -> FyydProvider:
    return FyydProvider()


def _items(payload: object) -> list[dict[str, object]]:
    return _provider()._payload_items(payload)


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "fyyd"
    assert p.tags == ["podcast", "media"]
    assert "no API key required" in p.description


def test_payload_items_filters_junk_and_checks_status() -> None:
    # The trailing "junk" string is not a record and is dropped.
    assert len(_items(_EPISODE_RESPONSE)) == 3
    assert all(isinstance(item, dict) for item in _items(_EPISODE_RESPONSE))
    assert _items(_EMPTY_RESPONSE) == []
    assert _items({}) == []
    assert _items(None) == []
    assert _items("junk") == []
    assert _items({"status": 1}) == []
    assert _items({"status": 1, "data": "junk"}) == []
    # fyyd reports errors with a status other than 1.
    assert _items({"status": 0, "msg": "Invalid parameter", "data": []}) == []


def test_parse_episodes_builds_structured_results() -> None:
    p = _provider()
    results = p._build_results(_items(_EPISODE_RESPONSE), 10, episodes=True)

    # The duplicated record collapses, and "junk" is filtered before parsing.
    assert [r.title for r in results] == ["LLMs are real, AI is fake", "pyinfra basics"]

    first = results[0]
    assert first.rank == 1
    assert first.source == "fyyd.de"
    assert first.provider == "fyyd"
    assert (
        first.url == "https://craphound.com/news/2026/09/27/llms-are-real-ai-is-fake/"
    )
    assert first.published_date == "2026-09-28"
    assert first.extra["type"] == "episode"
    assert first.extra["episode_id"] == 16021018
    assert first.extra["podcast_id"] == 1289
    assert first.extra["audio_url"] == "https://example.org/audio/doctorow-524.mp3"
    assert first.extra["content_type"] == "audio/mpeg"
    assert first.extra["duration"] is None
    assert first.extra["duration_seconds"] is None
    assert first.extra["fyyd_url"] == "https://fyyd.de/episode/16021018"
    assert "Audio available" in first.snippet
    assert "LLMs are real" in first.snippet
    # fyyd's "n/a" placeholder must not leak into the snippet.
    assert "n/a" not in first.snippet


def test_parse_episode_falls_back_to_fyyd_page_and_formats_duration() -> None:
    p = _provider()
    results = p._build_results(_items(_EPISODE_RESPONSE), 10, episodes=True)
    second = results[1]

    assert second.url == "https://fyyd.de/episode/16021019"
    assert second.extra["page_url"] is None
    assert second.extra["duration"] == "1:00:05"
    assert second.extra["duration_seconds"] == 3605
    assert second.extra["season"] == 2
    assert second.extra["episode"] == 7
    assert "S2E7" in second.snippet
    assert "Duration: 1:00:05" in second.snippet


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        ({"duration": 65}, "1:05"),
        ({"duration": 5}, "0:05"),
        ({"duration": 3661}, "1:01:01"),
        ({"duration": 0, "duration_string": "12:00"}, "12:00"),
        ({"duration": -3, "duration_string": "n/a"}, ""),
        ({"duration": None, "duration_string": "unknown"}, ""),
        ({"duration": "n/a", "duration_string": "n/a"}, ""),
        ({}, ""),
    ],
)
def test_duration_label(item: dict[str, object], expected: str) -> None:
    assert _provider()._duration_label(item) == expected


def test_parse_podcasts_builds_structured_results() -> None:
    p = _provider()
    results = p._build_results(_items(_PODCAST_RESPONSE), 10, episodes=False)

    assert len(results) == 1
    show = results[0]
    assert show.title == "The TWIML AI Podcast"
    assert show.url == "https://twimlai.com"
    assert show.published_date == "2026-09-16"
    assert show.extra["type"] == "podcast"
    assert show.extra["podcast_id"] == 78641
    assert show.extra["author"] == "Sam Charrington"
    assert show.extra["language"] == "en"
    assert show.extra["episode_count"] == 795
    assert show.extra["feed_url"] == "https://feeds.megaphone.fm/MLN2155636147"
    assert show.extra["categories"] == [203, 155]
    assert show.extra["rank"] == 280
    assert "Author: Sam Charrington" in show.snippet
    assert "Language: en" in show.snippet
    assert "Episodes: 795" in show.snippet


def test_parse_podcast_falls_back_to_fyyd_page() -> None:
    p = _provider()
    items: list[dict[str, object]] = [
        {
            "id": 7,
            "title": "No Website Show",
            "htmlURL": "",
            "url_fyyd": "https://fyyd.de/podcast/no-website-show/0",
        },
    ]
    results = p._build_results(items, 10, episodes=False)
    assert results[0].url == "https://fyyd.de/podcast/no-website-show/0"
    assert results[0].extra["website_url"] is None


def test_parse_skips_records_without_title_or_url() -> None:
    p = _provider()
    items: list[dict[str, object]] = [
        {"title": "", "url": "https://example.org/1"},
        {"title": "No id and no url", "url": "", "url_fyyd": ""},
    ]
    assert p._build_results(items, 10, episodes=True) == []
    assert p._build_results(items, 10, episodes=False) == []
    # A record with an id but no URLs still resolves through the fyyd page.
    with_id: list[dict[str, object]] = [{"id": 4, "title": "Fallback"}]
    results = p._build_results(with_id, 10, episodes=True)
    assert results[0].url == "https://fyyd.de/episode/4"
    show = p._build_results([{"id": 5, "title": "Show"}], 10, episodes=False)
    assert show[0].url == "https://fyyd.de/podcast/5"


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._build_results(_items(_EPISODE_RESPONSE), 1, episodes=True)) == 1
    assert len(p._build_results(_items(_PODCAST_RESPONSE), 1, episodes=False)) == 1


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_returns_episodes_without_fallback(respx_mock) -> None:
    import respx

    respx_mock.get(_EPISODE_URL).mock(
        return_value=respx.MockResponse(200, json=_EPISODE_RESPONSE)
    )
    podcast_route = respx_mock.get(_PODCAST_URL).mock(
        return_value=respx.MockResponse(200, json=_PODCAST_RESPONSE)
    )

    p = _provider()
    result = await p.search("llms", SearchParams(num_results=5))

    assert [r.title for r in result.results] == [
        "LLMs are real, AI is fake",
        "pyinfra basics",
    ]
    # Episodes won, so the show-level endpoint must not have been queried.
    assert not podcast_route.called
    assert len(respx_mock.calls) == 1
    params = dict(respx_mock.calls[0].request.url.params)
    assert params["term"] == "llms"
    assert params["count"] == "5"


@pytest.mark.asyncio
async def test_search_falls_back_to_podcasts(respx_mock) -> None:
    import respx

    respx_mock.get(_EPISODE_URL).mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE)
    )
    respx_mock.get(_PODCAST_URL).mock(
        return_value=respx.MockResponse(200, json=_PODCAST_RESPONSE)
    )

    p = _provider()
    result = await p.search("the twiml ai podcast", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["The TWIML AI Podcast"]
    assert result.results[0].extra["type"] == "podcast"
    assert len(respx_mock.calls) == 2
    urls = [str(call.request.url) for call in respx_mock.calls]
    assert any(url.startswith(_EPISODE_URL) for url in urls)
    assert any(url.startswith(_PODCAST_URL) for url in urls)


@pytest.mark.asyncio
async def test_search_error_status_falls_back_to_podcasts(respx_mock) -> None:
    import respx

    # fyyd answers malformed queries with status 0 rather than HTTP 4xx.
    respx_mock.get(_EPISODE_URL).mock(
        return_value=respx.MockResponse(
            200, json={"status": 0, "msg": "Invalid parameter"}
        )
    )
    respx_mock.get(_PODCAST_URL).mock(
        return_value=respx.MockResponse(200, json=_PODCAST_RESPONSE)
    )

    p = _provider()
    result = await p.search("!!", SearchParams(num_results=5))
    assert [r.title for r in result.results] == ["The TWIML AI Podcast"]


@pytest.mark.asyncio
async def test_search_blank_query_makes_no_request(respx_mock) -> None:
    import respx

    episode_route = respx_mock.get(_EPISODE_URL).mock(
        return_value=respx.MockResponse(200, json=_EPISODE_RESPONSE)
    )

    p = _provider()
    assert (await p.search("   ", SearchParams(num_results=5))).results == []
    assert not episode_route.called


@pytest.mark.asyncio
async def test_search_empty_for_both_endpoints(respx_mock) -> None:
    import respx

    respx_mock.get(_EPISODE_URL).mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE)
    )
    respx_mock.get(_PODCAST_URL).mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE)
    )

    p = _provider()
    result = await p.search("zzzqqxxnonexistent", SearchParams(num_results=5))
    assert result.results == []
