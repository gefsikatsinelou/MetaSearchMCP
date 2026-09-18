"""Unit tests for the MangaDex manga provider."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.mangadex import MangaDexProvider

_ENDPOINT = "https://api.mangadex.org/manga"
_MANGA_ID = "46e782ea-478a-4204-b83b-8da011c73ba5"

_MANGA: dict[str, Any] = {
    "id": _MANGA_ID,
    "type": "manga",
    "attributes": {
        "title": {"ja-ro": "Cowboy Bebop"},
        "altTitles": [
            {"en": "Cowboy Bebop"},
            {"ja": "カウボーイビバップ"},
        ],
        "description": {
            "en": (
                "Spike, Jet, Faye and Ed take odd jobs.\n\n"
                "Official Release:\n- Indonesian release"
            ),
        },
        "status": "completed",
        "year": 1998,
        "contentRating": "safe",
        "publicationDemographic": "shoujo",
        "lastChapter": "11",
        "lastVolume": "3",
        "originalLanguage": "ja",
        "availableTranslatedLanguages": ["en", "es", "fr"],
        "links": {"mal": "173", "al": "30173"},
        "tags": [
            {"attributes": {"name": {"en": "Sci-Fi"}, "group": "genre"}},
            {"attributes": {"name": {"en": "Action"}, "group": "genre"}},
            {"attributes": {"name": {"en": "Comedy"}, "group": "genre"}},
            {"attributes": {"name": {"en": "Adventure"}, "group": "genre"}},
            {"attributes": {"name": {"en": "Drama"}, "group": "genre"}},
            {"attributes": {"name": {"en": "Adaptation"}, "group": "format"}},
        ],
    },
    "relationships": [
        {"id": "a1", "type": "author", "attributes": {"name": "Nanten Yutaka"}},
        {"id": "a1", "type": "artist", "attributes": {"name": "Nanten Yutaka"}},
        {"id": "c1", "type": "cover_art", "attributes": {"fileName": "aea80759.png"}},
        {"id": "m2", "type": "manga", "related": "spin_off"},
    ],
}

_ONGOING: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000002",
    "type": "manga",
    "attributes": {
        "title": {"ja": "サンプル"},
        "altTitles": [],
        "description": {},
        "status": "ongoing",
        "year": None,
        "contentRating": "suggestive",
        "publicationDemographic": None,
        "lastChapter": None,
        "lastVolume": None,
    },
}

_EXPLICIT: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000003",
    "type": "manga",
    "attributes": {
        "title": {"en": "Explicit title"},
        "status": "completed",
        "year": 2020,
        "contentRating": "erotica",
        "lastChapter": "1",
    },
}


def _envelope(records: list[Any], total: int | None = 42) -> dict[str, Any]:
    """Wrap *records* in a MangaDex collection response envelope."""
    return {"result": "ok", "response": "collection", "data": records, "total": total}


def test_mangadex_name_tags_and_availability() -> None:
    p = MangaDexProvider()
    assert p.name == "mangadex"
    assert p.tags == ["manga", "media"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_mangadex_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "mangadex" in registry
    assert registry["mangadex"].tags == ["manga", "media"]


def test_mangadex_parse_record() -> None:
    p = MangaDexProvider()
    result = p._parse(_envelope([_MANGA]), limit=5)

    assert len(result.results) == 1
    r = result.results[0]
    # The English alternate title wins over the romaji primary title.
    assert r.title == "Cowboy Bebop"
    assert r.url == f"https://mangadex.org/title/{_MANGA_ID}"
    assert r.source == "mangadex.org"
    assert r.provider == "mangadex"
    assert r.rank == 1
    assert r.published_date == "1998"
    assert r.snippet == (
        "Completed | 1998 | 11 chapters | 3 volumes | Shoujo | "
        "Sci-Fi, Action, Comedy, Adventure | by Nanten Yutaka"
    )
    assert r.extra["mangadex_id"] == _MANGA_ID
    assert r.extra["titles"] == {"ja-ro": "Cowboy Bebop"}
    assert r.extra["alt_titles"] == ["Cowboy Bebop", "カウボーイビバップ"]
    assert r.extra["status"] == "completed"
    assert r.extra["year"] == 1998
    assert r.extra["content_rating"] == "safe"
    assert r.extra["publication_demographic"] == "shoujo"
    assert r.extra["last_chapter"] == "11"
    assert r.extra["last_volume"] == "3"
    assert r.extra["original_language"] == "ja"
    assert r.extra["authors"] == ["Nanten Yutaka"]
    assert r.extra["artists"] == ["Nanten Yutaka"]
    assert r.extra["tags"] == [
        "Sci-Fi",
        "Action",
        "Comedy",
        "Adventure",
        "Drama",
        "Adaptation",
    ]
    assert r.extra["available_translated_languages"] == ["en", "es", "fr"]
    assert r.extra["cover_image"] == (
        f"https://uploads.mangadex.org/covers/{_MANGA_ID}/aea80759.png.256.jpg"
    )
    assert r.extra["links"] == {"mal": "173", "al": "30173"}
    assert r.extra["total_results"] == 42


def test_mangadex_description_is_collapsed_and_truncated() -> None:
    p = MangaDexProvider()
    r = p._parse(_envelope([_MANGA])).results[0]
    assert r.extra["description"] == (
        "Spike, Jet, Faye and Ed take odd jobs. Official Release: - Indonesian release"
    )

    long_description = dict(_MANGA)
    long_description["attributes"] = dict(
        _MANGA["attributes"],
        description={"en": "word " * 400},
    )
    truncated = p._parse(_envelope([long_description])).results[0]
    assert len(truncated.extra["description"]) == 500


def test_mangadex_ongoing_record_without_optional_fields() -> None:
    p = MangaDexProvider()
    r = p._parse(_envelope([_ONGOING])).results[0]

    # Falls back to the only title MangaDex lists.
    assert r.title == "サンプル"
    assert r.published_date is None
    assert r.extra["description"] is None
    assert r.extra["cover_image"] is None
    assert r.extra["mangadex_id"] == "00000000-0000-0000-0000-000000000002"
    assert r.extra["authors"] == []
    assert r.extra["artists"] == []
    assert r.extra["tags"] == []
    # A suggestive record is still a "safe" search hit, so the rating is not
    # spelled out in the snippet.
    assert r.snippet == "Ongoing"


def test_mangadex_snippet_reveals_explicit_ratings() -> None:
    p = MangaDexProvider()
    r = p._parse(_envelope([_EXPLICIT])).results[0]
    assert r.snippet == "Completed | 2020 | 1 chapter | Erotica"


def test_mangadex_parse_skips_records_without_id_title_or_attributes() -> None:
    p = MangaDexProvider()
    payload = _envelope(
        [
            {"type": "manga"},
            {"id": "x", "attributes": "nope"},
            {"id": "y", "attributes": {"title": {}}},
            _MANGA,
        ]
    )
    results = p._parse(payload).results
    assert [r.title for r in results] == ["Cowboy Bebop"]
    assert results[0].rank == 1


def test_mangadex_parse_respects_limit() -> None:
    p = MangaDexProvider()
    payload = _envelope([_MANGA, _ONGOING, _EXPLICIT])
    assert len(p._parse(payload, limit=2).results) == 2


def test_mangadex_parse_empty_and_malformed() -> None:
    p = MangaDexProvider()
    assert p._parse(_envelope([])).results == []
    assert p._parse({}).results == []
    assert p._parse({"data": "nope"}).results == []
    assert p._parse({"data": [1, 2, 3]}).results == []
    assert p._parse({"errors": [{"message": "Invalid query"}]}).results == []
    assert p._parse([1, 2, 3]).results == []
    assert p._parse(None).results == []


def test_mangadex_parse_ignores_odd_field_types() -> None:
    p = MangaDexProvider()
    payload = _envelope(
        [
            {
                "id": "z",
                "attributes": {
                    "title": {"en": "  Spaced   title  "},
                    "altTitles": "nope",
                    "description": {"en": "  "},
                    "status": 5,
                    "year": True,
                    "contentRating": "safe",
                    "lastChapter": 11,
                    "tags": [{"attributes": {"name": {"en": ""}}}, "nope", {}],
                    "availableTranslatedLanguages": ["en", 7, ""],
                    "links": "nope",
                },
                "relationships": "nope",
            }
        ],
        total=None,
    )
    r = p._parse(payload).results[0]

    assert r.title == "Spaced title"
    assert r.extra["description"] is None
    assert r.extra["status"] is None
    assert r.extra["year"] is None
    assert r.extra["last_chapter"] is None
    assert r.extra["tags"] == []
    assert r.extra["available_translated_languages"] == ["en"]
    assert r.extra["links"] is None
    assert r.extra["cover_image"] is None
    assert r.extra["total_results"] is None
    assert r.snippet == ""


def test_mangadex_helpers() -> None:
    from metasearchmcp.providers.mangadex import (
        _alt_titles,
        _clean,
        _count,
        _cover,
        _int,
        _label,
        _localized,
        _relation_names,
        _strings,
        _tags,
        _title_candidates,
        _title_map,
    )

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _localized({"ja": "x", "en": "English"}) == "English"
    assert _localized({"ja": "x"}) == "x"
    assert _localized({"en": "  "}) == ""
    assert _localized("nope") == ""
    assert _int(1998) == 1998
    assert _int(True) is None
    assert _int("1998") is None
    assert _strings(["a", 3, "", "b"]) == ["a", "b"]
    assert _strings("nope") == []
    assert _label("shoujo") == "Shoujo"
    assert _label("suggestive") == "Suggestive"
    assert _label(None) == ""
    assert _title_map({"title": {"en": "A", "ja": " B "}}) == {"en": "A", "ja": "B"}
    assert _title_map({"title": "nope"}) == {}
    duplicates = {"altTitles": [{"en": "A"}, {"en": "A"}, "nope", {"ja": "B"}]}
    assert _alt_titles(duplicates) == ["A", "B"]
    assert _alt_titles({}) == []
    assert _title_candidates({"title": {"ja-ro": "R"}, "altTitles": [{"en": "E"}]}) == [
        "E",
        "R",
    ]
    same_title = {"title": {"en": "E"}, "altTitles": [{"en": "E"}]}
    assert _title_candidates(same_title) == ["E"]
    assert _title_candidates({"title": "nope", "altTitles": "nope"}) == []
    assert _relation_names(
        {"relationships": [{"type": " author ", "attributes": {"name": " A "}}, {}]},
        "author",
    ) == ["A"]
    assert _relation_names({"relationships": "nope"}, "author") == []
    assert _relation_names({}, "artist") == []
    assert (
        _cover(
            {
                "relationships": [
                    {"type": "cover_art", "attributes": {"fileName": "c.png"}}
                ]
            },
            "id",
        )
        == "https://uploads.mangadex.org/covers/id/c.png.256.jpg"
    )
    named_covers = _cover(
        {"relationships": [{"type": "cover_art", "attributes": {}}]},
        "id",
    )
    assert named_covers == ""
    assert _cover({}, "id") == ""
    assert _tags([{"attributes": {"name": {"en": "Action"}}}]) == ["Action"]
    assert _tags("nope") == []
    assert _count("11", "chapter") == "11 chapters"
    assert _count("1", "chapter") == "1 chapter"
    assert _count(None, "volume") == ""


async def test_mangadex_search_sends_expected_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope([_MANGA, _ONGOING]))
    )

    result = await MangaDexProvider().search(
        "cowboy bebop",
        SearchParams(num_results=5),
    )

    assert route.called
    params = route.calls[0].request.url.params
    assert params["title"] == "cowboy bebop"
    assert params["limit"] == "5"
    assert params["order[relevance]"] == "desc"
    assert params.get_list("includes[]") == ["cover_art", "author", "artist"]
    # A safe search still asks for suggestive records but not for erotica.
    assert params.get_list("contentRating[]") == ["safe", "suggestive"]

    assert [r.title for r in result.results] == ["Cowboy Bebop", "サンプル"]


async def test_mangadex_search_requests_explicit_ratings(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope([_MANGA]))
    )

    await MangaDexProvider().search("cowboy bebop", SearchParams(safe_search=False))

    params = route.calls[0].request.url.params
    assert params.get_list("contentRating[]") == [
        "safe",
        "suggestive",
        "erotica",
        "pornographic",
    ]


async def test_mangadex_search_caps_limit_to_api_maximum(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope([_MANGA]))
    )

    provider = MangaDexProvider()
    provider._max_results = 1000
    await provider.search("cowboy bebop", SearchParams(num_results=50))
    assert route.calls[0].request.url.params["limit"] == "50"

    provider._max_results = 500
    await provider.search("cowboy bebop", SearchParams(num_results=50))
    assert route.calls[1].request.url.params["limit"] == "50"


async def test_mangadex_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT)

    result = await MangaDexProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_mangadex_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(429))

    with pytest.raises(httpx.HTTPStatusError):
        await MangaDexProvider().search("cowboy bebop", SearchParams())
