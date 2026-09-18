"""Unit tests for the AniList anime and manga provider."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.anilist import AniListProvider

_ENDPOINT = "https://graphql.anilist.co"

_ANIME: dict[str, object] = {
    "id": 1,
    "idMal": 1,
    "type": "ANIME",
    "format": "TV",
    "status": "FINISHED",
    "season": "SPRING",
    "seasonYear": 1998,
    "title": {
        "romaji": "Cowboy Bebop",
        "english": "Cowboy Bebop",
        "native": "カウボーイビバップ",
    },
    "description": (
        "Enter a world <b>in the distant future</b>, where Bounty Hunters "
        "roam the solar system.<br><br>Spike and Jet take odd jobs."
    ),
    "startDate": {"year": 1998, "month": 4, "day": 3},
    "endDate": {"year": 1999},
    "episodes": 26,
    "chapters": None,
    "volumes": None,
    "duration": 24,
    "genres": ["Action", "Adventure", "Drama", "Sci-Fi"],
    "averageScore": 86,
    "meanScore": 85,
    "popularity": 468077,
    "favourites": 32217,
    "isAdult": False,
    "siteUrl": "https://anilist.co/anime/1",
    "coverImage": {
        "large": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/bx1.png",
    },
    "studios": {"nodes": [{"name": "Sunrise"}, {"name": "Bandai Visual"}]},
    "countryOfOrigin": "JP",
    "source": "ORIGINAL",
}

_MANGA: dict[str, object] = {
    "id": 30174,
    "idMal": 174,
    "type": "MANGA",
    "format": "MANGA",
    "status": "FINISHED",
    "season": None,
    "seasonYear": None,
    "title": {"romaji": "Shooting Star Bebop", "english": None, "native": None},
    "description": None,
    "startDate": {"year": 1998, "month": 5, "day": None},
    "endDate": {},
    "episodes": None,
    "chapters": 10,
    "volumes": 2,
    "duration": None,
    "genres": ["Action"],
    "averageScore": 59,
    "meanScore": None,
    "popularity": 1651,
    "favourites": 13,
    "isAdult": False,
    "siteUrl": None,
    "coverImage": None,
    "studios": {"nodes": []},
    "countryOfOrigin": "JP",
    "source": "OTHER",
}

_ADULT: dict[str, object] = {
    "id": 999,
    "type": "MANGA",
    "format": "MANGA",
    "status": "RELEASING",
    "title": {"romaji": "Adult title"},
    "siteUrl": "https://anilist.co/manga/999",
    "isAdult": True,
}


def _envelope(media: list[object], total: int | None = 5000) -> dict[str, object]:
    """Wrap *media* records in an AniList GraphQL response envelope."""
    return {
        "data": {
            "Page": {
                "pageInfo": {"total": total},
                "media": media,
            }
        }
    }


def test_anilist_name_tags_and_availability() -> None:
    p = AniListProvider()
    assert p.name == "anilist"
    assert p.tags == ["anime", "manga", "media"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_anilist_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "anilist" in registry
    assert registry["anilist"].tags == ["anime", "manga", "media"]


def test_anilist_parse_anime_record() -> None:
    p = AniListProvider()
    result = p._parse(_envelope([_ANIME]), limit=5)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Cowboy Bebop"
    assert r.url == "https://anilist.co/anime/1"
    assert r.source == "anilist.co"
    assert r.provider == "anilist"
    assert r.rank == 1
    assert r.published_date == "1998-04-03"
    assert r.snippet == (
        "Anime TV | Finished | 1998 | 26 episodes | Action, Adventure, Drama, "
        "Sci-Fi | score 86/100 | 468077 AniList users | by Sunrise, Bandai Visual"
    )
    assert r.extra["anilist_id"] == 1
    assert r.extra["mal_id"] == 1
    assert r.extra["media_type"] == "ANIME"
    assert r.extra["format"] == "TV"
    assert r.extra["status"] == "FINISHED"
    assert r.extra["season"] == "Spring 1998"
    assert r.extra["titles"]["native"] == "カウボーイビバップ"
    assert r.extra["genres"] == ["Action", "Adventure", "Drama", "Sci-Fi"]
    assert r.extra["average_score"] == 86
    assert r.extra["mean_score"] == 85
    assert r.extra["episodes"] == 26
    assert r.extra["duration_minutes"] == 24
    assert r.extra["studios"] == ["Sunrise", "Bandai Visual"]
    assert r.extra["country_of_origin"] == "JP"
    assert r.extra["source"] == "ORIGINAL"
    assert r.extra["is_adult"] is False
    assert r.extra["end_date"] == "1999"
    assert r.extra["total_results"] == 5000


def test_anilist_description_is_html_stripped() -> None:
    p = AniListProvider()
    r = p._parse(_envelope([_ANIME])).results[0]
    assert r.extra["description"] == (
        "Enter a world in the distant future, where Bounty Hunters roam the "
        "solar system. Spike and Jet take odd jobs."
    )


def test_anilist_description_is_truncated() -> None:
    p = AniListProvider()
    record = dict(_ANIME, description="<p>" + ("word " * 400) + "</p>")
    r = p._parse(_envelope([record])).results[0]
    assert len(r.extra["description"]) == 500


def test_anilist_parse_manga_record_uses_fallback_url() -> None:
    p = AniListProvider()
    r = p._parse(_envelope([_MANGA])).results[0]

    # No English title, so the romaji title is used.
    assert r.title == "Shooting Star Bebop"
    # No siteUrl, so the record falls back to the id-based manga path.
    assert r.url == "https://anilist.co/manga/30174"
    # Only the month is known, so the date keeps the year-month prefix.
    assert r.published_date == "1998-05"
    assert r.snippet == (
        "Manga | Finished | 1998 | 10 chapters | 2 volumes | Action | "
        "score 59/100 | 1651 AniList users"
    )
    assert r.extra["episodes"] is None
    assert r.extra["duration_minutes"] is None
    assert r.extra["description"] is None
    assert r.extra["studios"] == []
    assert r.extra["season"] is None
    assert r.extra["end_date"] is None
    assert r.extra["cover_image"] is None


def test_anilist_parse_drops_adult_records_when_excluded() -> None:
    p = AniListProvider()
    payload = _envelope([_ADULT, _ANIME])

    kept = p._parse(payload).results
    assert [r.title for r in kept] == ["Adult title", "Cowboy Bebop"]

    filtered = p._parse(payload, include_adult=False).results
    assert [r.title for r in filtered] == ["Cowboy Bebop"]
    # Ranks are assigned after filtering, so the survivor is rank 1.
    assert filtered[0].rank == 1


def test_anilist_parse_skips_records_without_title_or_url() -> None:
    p = AniListProvider()
    payload = _envelope(
        [
            {"id": 2, "type": "ANIME"},
            {"title": {"romaji": "No link"}},
            *[_ANIME],
        ]
    )
    results = p._parse(payload).results
    assert [r.title for r in results] == ["Cowboy Bebop"]
    assert results[0].rank == 1


def test_anilist_parse_respects_limit() -> None:
    p = AniListProvider()
    payload = _envelope([_ANIME, _MANGA, _ANIME])
    assert len(p._parse(payload, limit=2).results) == 2


def test_anilist_parse_empty_and_malformed() -> None:
    p = AniListProvider()
    assert p._parse(_envelope([])).results == []
    assert p._parse({}).results == []
    assert p._parse({"data": "nope"}).results == []
    assert p._parse({"data": {"Page": "nope"}}).results == []
    assert p._parse({"data": {"Page": {"media": "nope"}}}).results == []
    assert p._parse({"errors": [{"message": "Invalid query"}]}).results == []
    assert p._parse([1, 2, 3]).results == []
    assert p._parse(None).results == []


def test_anilist_parse_skips_non_dict_records_and_odd_fields() -> None:
    p = AniListProvider()
    payload = _envelope(
        [
            "not-a-dict",
            {
                "id": 7,
                "siteUrl": "https://anilist.co/anime/7",
                "title": {"romaji": "  Spaced   title  "},
                "genres": ["Action", 5, ""],
                "episodes": True,
                "popularity": "many",
                "studios": {"nodes": ["nope", {}, {"name": " Trigger "}]},
                "isAdult": "yes",
                "startDate": {"month": 4},
            },
        ],
        total=None,
    )
    results = p._parse(payload).results

    assert [r.title for r in results] == ["Spaced title"]
    r = results[0]
    assert r.extra["genres"] == ["Action"]
    # Boolean episode counts are rejected, as are non-integer popularity values.
    assert r.extra["episodes"] is None
    assert r.extra["popularity"] is None
    assert r.extra["studios"] == ["Trigger"]
    # A non-boolean adult flag is reported as unknown.
    assert r.extra["is_adult"] is None
    assert r.published_date is None
    assert r.extra["total_results"] is None
    assert r.snippet == "Action | by Trigger"


def test_anilist_helpers() -> None:
    from metasearchmcp.providers.anilist import (
        _clean,
        _cover,
        _date,
        _format_label,
        _int,
        _season,
        _strings,
        _studios,
        _text,
        _titles,
    )

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _text("<p>a &amp; b</p><br/>c") == "a & b c"
    assert _text(None) == ""
    assert _int(5) == 5
    assert _int(True) is None
    assert _int("5") is None
    assert _strings(["a", 3, "", "b"]) == ["a", "b"]
    assert _strings("nope") == []
    assert _titles({"romaji": "r", "english": "", "native": "n"}) == {
        "romaji": "r",
        "native": "n",
    }
    assert _titles("nope") == {}
    assert _date({"year": 1998}) == "1998"
    assert _date({"year": 1998, "month": 4}) == "1998-04"
    assert _date({"year": 1998, "month": 4, "day": 3}) == "1998-04-03"
    assert _date({"month": 4}) is None
    assert _date(None) is None
    assert _studios({"nodes": [{"name": "Sunrise"}]}) == ["Sunrise"]
    assert _studios({"nodes": "nope"}) == []
    assert _studios(None) == []
    assert _cover({"large": "https://x/y.png"}) == "https://x/y.png"
    assert _cover(None) == ""
    assert _format_label("tv") == "TV"
    assert _format_label("ONE_SHOT") == "One Shot"
    assert _format_label("light_novel") == "Light Novel"
    assert _format_label("") == ""
    assert _season({"season": "fall", "seasonYear": 1998}) == "Fall 1998"
    assert _season({"season": "fall"}) == "Fall"
    assert _season({}) is None


async def test_anilist_search_posts_graphql_request(respx_mock) -> None:
    route = respx_mock.post(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope([_ANIME, _MANGA]))
    )

    result = await AniListProvider().search("bebop", SearchParams(num_results=5))

    assert route.called
    request = route.calls[0].request
    body = json.loads(request.content)
    assert body["variables"] == {"search": "bebop", "page": 1, "perPage": 5}
    assert "media(search: $search" in body["query"]

    assert [r.title for r in result.results] == [
        "Cowboy Bebop",
        "Shooting Star Bebop",
    ]
    assert result.results[0].provider == "anilist"


async def test_anilist_search_caps_per_page_to_api_limit(respx_mock) -> None:
    route = respx_mock.post(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope([_ANIME]))
    )

    provider = AniListProvider()
    # A provider configured for far more results still respects AniList's cap.
    provider._max_results = 1000
    await provider.search("bebop", SearchParams(num_results=50))

    body = json.loads(route.calls[0].request.content)
    assert body["variables"]["perPage"] == 50


async def test_anilist_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.post(_ENDPOINT)

    result = await AniListProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_anilist_search_respects_safe_search(respx_mock) -> None:
    respx_mock.post(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope([_ADULT, _ANIME]))
    )
    provider = AniListProvider()

    safe = await provider.search("bebop", SearchParams(safe_search=True))
    assert [r.title for r in safe.results] == ["Cowboy Bebop"]

    unsafe = await provider.search("other", SearchParams(safe_search=False))
    assert [r.title for r in unsafe.results] == ["Adult title", "Cowboy Bebop"]


async def test_anilist_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.post(_ENDPOINT).mock(return_value=respx.MockResponse(429))

    with pytest.raises(httpx.HTTPStatusError):
        await AniListProvider().search("bebop", SearchParams())
