"""Unit tests for the Library of Congress (loc.gov) search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.loc_gov import LocGovProvider

_SAMPLE_RESPONSE = {
    "search": {"hits": 2, "query": "baseball"},
    "pagination": {"of": 2, "perpage": 10},
    "results": [
        {
            "title": (
                "Explore | Baseball Americana | Exhibitions at the Library of Congress"
            ),
            "id": "http://www.loc.gov/exhibitions/baseball-americana/about-this-exhibition/",
            "url": "https://www.loc.gov/exhibitions/baseball-americana/about-this-exhibition/",
            "date": "",
            "timestamp": "2026-08-24T07:10:50.977Z",
            "original_format": ["exhibition"],
            "online_format": ["image"],
            "subject": ["baseball", "sports & recreation", "american history"],
            "description": [
                (
                    "Americans had been playing baseball long before they agreed "
                    "on the rules or even settled on how to spell it."
                )
            ],
        },
        {
            "title": "Baseball Resources at the Library of Congress",
            "id": "http://www.loc.gov/resource/abc.12345/",
            "url": "https://www.loc.gov/resource/abc.12345/",
            "date": "2021-05-24",
            "timestamp": "2026-08-22T23:36:37.188Z",
            "original_format": ["web page"],
            "subject": ["baseball", "jackie robinson"],
            "description": ["A comprehensive guide to baseball collections."],
        },
    ],
}


def _provider() -> LocGovProvider:
    return LocGovProvider()


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert (
        r.title
        == "Explore | Baseball Americana | Exhibitions at the Library of Congress"
    )
    assert (
        r.url
        == "https://www.loc.gov/exhibitions/baseball-americana/about-this-exhibition/"
    )
    assert r.provider == "loc_gov"
    assert r.source == "loc.gov"
    assert r.rank == 1
    assert r.published_date == "2026-08-24"  # derived from timestamp
    assert "Format: exhibition" in r.snippet
    assert "Subjects: baseball, sports & recreation, american history" in r.snippet
    assert r.extra["formats"] == ["exhibition"]
    assert r.extra["subjects"] == [
        "baseball",
        "sports & recreation",
        "american history",
    ]
    assert (
        r.extra["id"]
        == "http://www.loc.gov/exhibitions/baseball-americana/about-this-exhibition/"
    )


def test_parse_uses_explicit_date_when_present() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert result.results[1].published_date == "2021-05-24"


def test_parse_skips_entries_without_title_or_url() -> None:
    data = {
        "results": [
            {"title": "  ", "url": "https://www.loc.gov/item/x/"},
            {"title": "T", "url": ""},
            {"title": "T", "url": "https://www.loc.gov/item/y/"},
            "not-a-dict",
            None,
        ],
    }
    result = _provider()._parse(data)
    assert len(result.results) == 1
    assert result.results[0].url == "https://www.loc.gov/item/y/"
    assert _provider()._parse({}).results == []
    assert _provider()._parse({"results": "not-a-list"}).results == []


def test_parse_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, max_results=1)
    assert len(result.results) == 1
    assert result.results[0].published_date == "2026-08-24"


def test_first_string_helpers() -> None:
    assert LocGovProvider._first_string(["a", "b"]) == "a"
    assert LocGovProvider._first_string(["", "  ", "b"]) == "b"
    assert LocGovProvider._first_string("  spaced  ") == "spaced"
    assert LocGovProvider._first_string(None) == ""
    assert LocGovProvider._first_string(42) == "42"


def test_clean_list_dedupes() -> None:
    assert LocGovProvider._clean_list(["A", "a", "b", "", " c "]) == ["A", "b", "c"]
    assert LocGovProvider._clean_list(None) == []
    assert LocGovProvider._clean_list("not-a-list") == []


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_endpoint(respx_mock) -> None:
    import respx

    respx_mock.get("https://www.loc.gov/search/").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("baseball", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "loc_gov"
    assert result.results[0].url.startswith("https://www.loc.gov/")
