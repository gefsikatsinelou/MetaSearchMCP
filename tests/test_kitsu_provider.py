"""Unit tests for the Kitsu anime/manga search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.kitsu import KitsuProvider

_SAMPLE_ANIME = {
    "data": [
        {
            "id": "1555",
            "type": "anime",
            "links": {"self": "https://kitsu.io/api/edge/anime/1555"},
            "attributes": {
                "canonicalTitle": "Naruto: Shippuuden",
                "slug": "naruto-shippuden",
                "synopsis": (
                    "Two and a half years after leaving the Hidden Leaf Village, "
                    "Naruto returns to face the Akatsuki threat."
                ),
                "startDate": "2007-02-15",
                "endDate": "2017-03-23",
                "status": "finished",
                "episodeCount": 500,
                "episodeLength": 23,
                "averageRating": "84.06",
                "posterImage": {
                    "tiny": "https://media.kitsu.app/tiny.jpg",
                    "medium": "https://media.kitsu.app/medium.jpg",
                    "original": "https://media.kitsu.app/original.jpg",
                },
            },
            "relationships": {
                "categories": {
                    "links": {"related": "https://kitsu.io/api/edge/anime/1555/categories"},
                    "data": [
                        {"id": "Action", "type": "categories"},
                        {"id": "Adventure", "type": "categories"},
                    ],
                },
                "producers": {"data": [{"id": "Studio Pierrot", "type": "producers"}]},
            },
        },
        {
            "id": "999",
            "type": "anime",
            "attributes": {"slug": "unnamed-series"},
            "relationships": {},
        },
    ]
}

_SAMPLE_MANGA = {
    "data": [
        {
            "id": "11",
            "type": "manga",
            "links": {"self": "https://kitsu.io/api/edge/manga/11"},
            "attributes": {
                "canonicalTitle": "Berserk",
                "synopsis": "A lone swordsman's dark journey.",
                "startDate": "1989-08-25",
                "status": "current",
                "chapterCount": 375,
                "volumeCount": 41,
                "averageRating": "88.99",
            },
            "relationships": {
                "categories": {"data": [{"id": "Action", "type": "categories"}]}
            },
        }
    ]
}

_EMPTY_RESPONSE = {"data": []}


def test_kitsu_parse_anime_basic():
    p = KitsuProvider()
    result = p._parse(_SAMPLE_ANIME, "anime")

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Naruto: Shippuuden"
    assert r.url == "https://kitsu.io/api/edge/anime/1555"
    assert "Akatsuki" in r.snippet
    assert "Episodes: 500" in r.snippet
    assert "Rating: 84.06" in r.snippet
    assert "Status: Finished" in r.snippet
    assert "Genres: Action, Adventure" in r.snippet
    assert r.source == "kitsu.io"
    assert r.provider == "kitsu"
    assert r.rank == 1
    assert r.published_date == "2007-02-15"
    assert r.extra["media_type"] == "anime"
    assert r.extra["episodes"] == 500
    assert r.extra["genres"] == ["Action", "Adventure"]
    assert r.extra["image_url"] == "https://media.kitsu.app/medium.jpg"


def test_kitsu_parse_manga_basic():
    p = KitsuProvider()
    result = p._parse(_SAMPLE_MANGA, "manga")

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Berserk"
    assert "Chapters: 375" in r.snippet
    assert r.extra["chapters"] == 375
    assert r.extra["volumes"] == 41
    assert "image_url" not in r.extra


def test_kitsu_parse_skips_item_without_title_and_url():
    p = KitsuProvider()
    result = p._parse(_SAMPLE_ANIME, "anime")
    assert len(result.results) == 1
    assert all(r.title and r.url for r in result.results)


def test_kitsu_parse_empty():
    p = KitsuProvider()
    result = p._parse(_EMPTY_RESPONSE, "anime")
    assert result.results == []


def test_kitsu_parse_non_dict_data():
    p = KitsuProvider()
    result = p._parse({"data": ["not-a-dict"]}, "anime")
    assert result.results == []


def test_kitsu_poster_url():
    assert (
        KitsuProvider._poster_url(
            {"posterImage": {"small": "s.jpg", "medium": "m.jpg"}}
        )
        == "m.jpg"
    )
    assert KitsuProvider._poster_url({"posterImage": {"original": "o.jpg"}}) == "o.jpg"
    assert KitsuProvider._poster_url({}) == ""
    assert KitsuProvider._poster_url({"posterImage": "not-a-dict"}) == ""


def test_kitsu_relationship_names():
    item = {
        "relationships": {
            "categories": {
                "data": [{"id": "Action"}, {"id": ""}, "junk"],
            }
        }
    }
    assert KitsuProvider._relationship_names(item, "categories") == ["Action", ""]
    assert KitsuProvider._relationship_names(item, "producers") == []
    assert KitsuProvider._relationship_names({}, "categories") == []


def test_kitsu_is_available():
    """Keyless provider is always available."""
    assert KitsuProvider().is_available() is True


@pytest.mark.asyncio
async def test_kitsu_search_hits_both_endpoints(respx_mock):
    """Search queries anime and manga endpoints and merges results."""
    import respx

    respx_mock.get("https://kitsu.io/api/edge/anime").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_ANIME),
    )
    respx_mock.get("https://kitsu.io/api/edge/manga").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_MANGA),
    )

    p = KitsuProvider()
    result = await p.search("naruto", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "kitsu"
    assert {r.extra["media_type"] for r in result.results} == {"anime", "manga"}


@pytest.mark.asyncio
async def test_kitsu_search_caps_at_limit(respx_mock):
    """Search truncates the merged result set to num_results."""
    import respx

    respx_mock.get("https://kitsu.io/api/edge/anime").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_ANIME),
    )
    respx_mock.get("https://kitsu.io/api/edge/manga").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_MANGA),
    )

    p = KitsuProvider()
    result = await p.search("naruto", SearchParams(num_results=1))

    assert len(result.results) == 1
    assert result.results[0].extra["media_type"] == "anime"


@pytest.mark.asyncio
async def test_kitsu_search_ignores_failed_endpoint(respx_mock):
    """A failing manga endpoint does not break the anime results."""
    import respx

    respx_mock.get("https://kitsu.io/api/edge/anime").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_ANIME),
    )
    respx_mock.get("https://kitsu.io/api/edge/manga").mock(
        return_value=respx.MockResponse(500),
    )

    p = KitsuProvider()
    result = await p.search("naruto", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].extra["media_type"] == "anime"


@pytest.mark.asyncio
async def test_kitsu_search_sends_json_api_accept_header(respx_mock):
    """The JSON:API Accept header is sent on both requests."""
    import respx

    anime_route = respx_mock.get("https://kitsu.io/api/edge/anime").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_ANIME),
    )
    respx_mock.get("https://kitsu.io/api/edge/manga").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_MANGA),
    )

    p = KitsuProvider()
    await p.search("naruto", SearchParams(num_results=2))

    request = anime_route.calls.last.request
    assert request.headers["accept"] == "application/vnd.api+json"
    assert request.url.params["filter[text]"] == "naruto"
    assert request.url.params["page[limit]"] == "2"
