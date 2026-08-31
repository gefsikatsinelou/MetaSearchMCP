"""Unit tests for the Spaceflight News API search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.spaceflight_news import SpaceflightNewsProvider

_SAMPLE_RESPONSE: dict[str, object] = {
    "count": 3,
    "results": [
        {
            "id": 39739,
            "title": "Roman lifts off on a mission to survey the infrared sky",
            "authors": [{"name": "ESA", "socials": None}],
            "url": "https://www.esa.int/ESA_Multimedia/Images/2026/08/roman",
            "news_site": "ESA",
            "summary": (
                "The Nancy Grace Roman Space Telescope lifted off on a Falcon Heavy."
            ),
            "published_at": "2026-08-31T07:00:00Z",
        },
        {
            "id": 37429,
            "title": "Starship completes fifth test flight",
            "authors": [
                {"name": "SpaceX", "socials": None},
                {"name": "Ars Technica", "socials": None},
            ],
            "url": "https://example.com/starship",
            "news_site": "Example News",
            "summary": "",
            "published_at": "2026-07-20T12:30:00Z",
        },
        {
            # Missing URL -> skipped.
            "id": 999,
            "title": "Incomplete article",
            "news_site": "Junk",
        },
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"count": 0, "results": []}


def _provider() -> SpaceflightNewsProvider:
    return SpaceflightNewsProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "spaceflight_news"
    assert p.tags == ["news", "space", "web"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Roman lifts off on a mission to survey the infrared sky"
    assert r.url == "https://www.esa.int/ESA_Multimedia/Images/2026/08/roman"
    assert "Falcon Heavy" in r.snippet
    assert "Source: ESA" in r.snippet
    assert "By: ESA" in r.snippet
    assert r.provider == "spaceflight_news"
    assert r.source == "ESA"
    assert r.rank == 1
    assert r.published_date == "2026-08-31"
    assert r.extra["authors"] == ["ESA"]
    assert r.extra["news_site"] == "ESA"


def test_parse_second_article() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    r = result.results[1]
    assert r.title == "Starship completes fifth test flight"
    assert r.rank == 2
    assert r.published_date == "2026-07-20"
    assert r.extra["authors"] == ["SpaceX", "Ars Technica"]
    assert "By: SpaceX, Ars Technica" in r.snippet
    assert r.extra["news_site"] == "Example News"


def test_parse_skips_incomplete() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert all(r.title and r.url for r in result.results)


def test_parse_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1
    assert result.results[0].title == (
        "Roman lifts off on a mission to survey the infrared sky"
    )


def test_parse_empty_and_malformed() -> None:
    assert _provider()._parse(_EMPTY_RESPONSE).results == []
    assert _provider()._parse({"results": None}).results == []
    assert _provider()._parse({"results": "junk"}).results == []
    assert _provider()._parse({}).results == []
    assert _provider()._parse(None).results == []


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.spaceflightnewsapi.net/v4/articles").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("roman", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "spaceflight_news"
    request = respx_mock.calls.last.request
    assert request.url.params["search"] == "roman"
    assert request.url.params["limit"] == "5"


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.spaceflightnewsapi.net/v4/articles").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("zzz", SearchParams(num_results=5))
    assert result.results == []
