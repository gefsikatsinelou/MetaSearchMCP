"""Unit tests for the WordPress.org theme directory search provider."""

from __future__ import annotations

import httpx
import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.wordpress_themes import WordPressThemesProvider

_SEARCH_RESPONSE: dict[str, object] = {
    "info": {"page": 1, "pages": 1, "results": 2},
    "themes": [
        {
            "name": "Astra",
            "slug": "astra",
            "version": "4.8.12",
            "author": {
                "user_nicename": "brainstormforce",
                "display_name": "Brainstorm Force",
            },
            "requires": "5.9",
            "tested": "6.8",
            "rating": 98,
            "num_ratings": 6498,
            "downloaded": 25013585,
            "last_updated": "2026-08-31 1:04pm GMT",
            "homepage": "https://wpastra.com/",
            "description": (
                "Astra is fast, fully customizable & beautiful WordPress "
                "theme suitable for blogs, portfolios and business."
            ),
            "tags": {"blog": "blog", "business": "business"},
            "screenshot_url": "https://ps.w.org/astra/assets/screenshot.png",
            "download_link": "https://downloads.wordpress.org/theme/astra.zip",
        },
        {
            "name": "Niche Blog Fork",
            "slug": "niche-blog-fork",
            "version": "0.1.0",
            # Lower download count: should be re-ranked after the canonical theme.
            "downloaded": 500,
            "num_ratings": 2,
            "rating": 100,
            "last_updated": "junk-date",
            "author": "Plain Author",
        },
        {"slug": "no-name-hit"},
        "junk",  # type: ignore[list-item]
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"info": {"results": 0}, "themes": []}


def _provider() -> WordPressThemesProvider:
    return WordPressThemesProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "wordpress_themes"
    assert p.tags == ["web", "code", "developer", "plugins"]
    assert "no API key required" in p.description


def test_parse_basic_hit_fields() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)

    assert len(result.results) == 3
    first = result.results[0]
    assert first.title == "Astra"
    assert first.url == "https://wordpress.org/themes/astra/"
    assert first.source == "wordpress.org"
    assert first.provider == "wordpress_themes"
    assert first.rank == 1
    assert "fully customizable" in first.snippet
    assert "v4.8.12" in first.snippet
    assert "Downloads: 25,013,585" in first.snippet
    assert "Rating: 4.9/5 (6498)" in first.snippet
    assert "Author: Brainstorm Force" in first.snippet
    assert first.published_date == "2026-08-31"
    assert first.extra["slug"] == "astra"
    assert first.extra["author"] == "Brainstorm Force"
    assert first.extra["rating"] == 4.9
    assert first.extra["rating_count"] == 6498
    assert first.extra["total_downloads"] == 25013585
    # Localized datetime format is parsed too.
    assert first.extra["last_updated"] == "2026-08-31"
    assert first.extra["tags"] == ["blog", "business"]
    assert first.extra["screenshot_url"].startswith("https://ps.w.org/")


def test_parse_slug_only_record_falls_back_to_slug_title() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    # A record with a slug but no name is kept with the slug as its title.
    third = result.results[2]
    assert third.title == "no-name-hit"
    assert third.url == "https://wordpress.org/themes/no-name-hit/"
    assert third.extra["total_downloads"] == 0


def test_parse_reranks_by_popularity() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    # Canonical (high-download) theme surfaces before the niche fork.
    assert result.results[0].extra["slug"] == "astra"
    assert result.results[1].extra["slug"] == "niche-blog-fork"


def test_parse_handles_missing_fields() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    second = result.results[1]
    assert second.title == "Niche Blog Fork"
    assert second.published_date is None
    assert second.extra["last_updated"] is None
    assert second.extra["rating"] == 5.0
    assert second.extra["requires_wp"] == ""
    assert second.extra["screenshot_url"] == ""
    # Plain-string author (not a dict) is handled too.
    assert second.extra["author"] == "Plain Author"


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []
    assert p._parse(None).results == []
    assert p._parse("junk").results == []
    assert p._parse({"themes": "junk"}).results == []
    assert p._parse({"themes": [{}]}).results == []
    assert p._parse({"themes": [{"name": ""}]}).results == []


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse(_SEARCH_RESPONSE, limit=1).results) == 1


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_gets_api(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.wordpress.org/themes/info/1.2/").mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE)
    )

    p = _provider()
    result = await p.search("blog", SearchParams(num_results=5))

    assert len(result.results) == 3
    assert result.results[0].title == "Astra"
    call = respx_mock.calls[0]
    assert "action=query_themes" in str(call.request.url)
    # httpx URL-encodes the bracketed request params.
    assert "request%5Bsearch%5D=blog" in str(call.request.url)
    assert "request%5Bper_page%5D=5" in str(call.request.url)
    # Popularity fields are explicitly requested from the Themes API.
    assert "request%5Bfields%5D%5Bdownloaded%5D=true" in str(call.request.url)


@pytest.mark.asyncio
async def test_search_http_error_raises(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.wordpress.org/themes/info/1.2/").mock(
        return_value=respx.MockResponse(500)
    )

    p = _provider()
    with pytest.raises(httpx.HTTPStatusError):
        await p.search("blog", SearchParams(num_results=5))
