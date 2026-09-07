"""Unit tests for the WordPress.org plugin directory search provider."""

from __future__ import annotations

import httpx
import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.wordpress_plugins import WordPressPluginsProvider

_SEARCH_RESPONSE: dict[str, object] = {
    "info": {"page": 1, "pages": 1, "results": 1},
    "plugins": [
        {
            "name": "Rank Math SEO &#8211; AI SEO Tools",
            "slug": "seo-by-rank-math",
            "version": "1.0.277.2",
            "author": (
                '<a href="https://profiles.wordpress.org/rankmath/">Rank Math SEO</a>'
            ),
            "requires": "6.7",
            "requires_php": "7.4",
            "tested": "7.1",
            "rating": 96,
            "num_ratings": 7498,
            "active_installs": 4000000,
            "downloaded": 195088787,
            "added": "2018-11-19",
            "last_updated": "2026-08-31 1:04pm GMT",
            "homepage": "https://rankmath.com/",
            "short_description": (
                "Grow your organic traffic with powerful SEO tools, "
                "XML sitemaps, and Schema automation."
            ),
            "tags": {"seo": "seo", "analytics": "analytics"},
            "icons": {
                "1x": "https://ps.w.org/seo-by-rank-math/assets/icon-128x128.jpg",
                "2x": "https://ps.w.org/seo-by-rank-math/assets/icon-256x256.jpg",
            },
            "download_link": "https://downloads.wordpress.org/plugin/seo-by-rank-math.zip",
        },
        {
            "name": "Niche SEO Fork",
            "slug": "niche-seo-fork",
            "version": "0.1.0",
            # Lower install count: should be re-ranked after the canonical plugin.
            "active_installs": 20,
            "downloaded": 500,
            "added": "not-a-date",
        },
        {"slug": "no-name-hit"},
        "junk",  # type: ignore[list-item]
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"info": {"results": 0}, "plugins": []}


def _provider() -> WordPressPluginsProvider:
    return WordPressPluginsProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "wordpress_plugins"
    assert p.tags == ["web", "code", "developer", "plugins"]
    assert "no API key required" in p.description


def test_parse_basic_hit_fields() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)

    assert len(result.results) == 3
    first = result.results[0]
    assert first.title == "Rank Math SEO \u2013 AI SEO Tools"
    assert first.url == "https://wordpress.org/plugins/seo-by-rank-math/"
    assert first.source == "wordpress.org"
    assert first.provider == "wordpress_plugins"
    assert first.rank == 1
    assert "SEO tools" in first.snippet
    assert "v1.0.277.2" in first.snippet
    assert "Active installs: 4,000,000+" in first.snippet
    assert "Rating: 4.8/5 (7498)" in first.snippet
    assert "Requires WP: 6.7" in first.snippet
    assert "Author: Rank Math SEO" in first.snippet
    assert first.published_date == "2018-11-19"
    assert first.extra["slug"] == "seo-by-rank-math"
    assert first.extra["author"] == "Rank Math SEO"
    assert first.extra["rating"] == 4.8
    assert first.extra["rating_count"] == 7498
    assert first.extra["active_installs"] == 4000000
    assert first.extra["total_downloads"] == 195088787
    assert first.extra["added"] == "2018-11-19"
    # Localized datetime format is parsed too.
    assert first.extra["last_updated"] == "2026-08-31"
    assert first.extra["tags"] == ["seo", "analytics"]
    assert first.extra["icon"].startswith("https://ps.w.org/")


def test_parse_slug_only_record_falls_back_to_slug_title() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    # A record with a slug but no name is kept with the slug as its title.
    third = result.results[2]
    assert third.title == "no-name-hit"
    assert third.url == "https://wordpress.org/plugins/no-name-hit/"
    assert third.extra["active_installs"] == 0


def test_parse_reranks_by_popularity() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    # Canonical (high-install) plugin surfaces before the niche fork.
    assert result.results[0].extra["slug"] == "seo-by-rank-math"
    assert result.results[1].extra["slug"] == "niche-seo-fork"


def test_parse_handles_missing_fields() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    second = result.results[1]
    assert second.title == "Niche SEO Fork"
    assert second.published_date is None
    assert second.extra["added"] is None
    assert second.extra["last_updated"] is None
    assert second.extra["rating"] is None
    # The fork carries a version; other sparse fields fall back to defaults.
    assert second.extra["version"] == "0.1.0"
    assert second.extra["author"] == ""


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []
    assert p._parse(None).results == []
    assert p._parse("junk").results == []
    assert p._parse({"plugins": "junk"}).results == []
    assert p._parse({"plugins": [{}]}).results == []
    assert p._parse({"plugins": [{"name": ""}]}).results == []


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse(_SEARCH_RESPONSE, limit=1).results) == 1


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_gets_api(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.wordpress.org/plugins/info/1.2/").mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE)
    )

    p = _provider()
    result = await p.search("seo", SearchParams(num_results=5))

    assert len(result.results) == 3
    assert result.results[0].title.startswith("Rank Math SEO")
    call = respx_mock.calls[0]
    assert "action=query_plugins" in str(call.request.url)
    # httpx URL-encodes the bracketed request params.
    assert "request%5Bsearch%5D=seo" in str(call.request.url)
    assert "request%5Bper_page%5D=5" in str(call.request.url)


@pytest.mark.asyncio
async def test_search_http_error_raises(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.wordpress.org/plugins/info/1.2/").mock(
        return_value=respx.MockResponse(500)
    )

    p = _provider()
    with pytest.raises(httpx.HTTPStatusError):
        await p.search("seo", SearchParams(num_results=5))
