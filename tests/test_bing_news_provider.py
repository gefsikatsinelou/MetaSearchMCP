"""Unit tests for the Bing News RSS provider."""

# Long XML fixture lines are intentional; keep them readable as-is.
# ruff: noqa: E501

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.bing_news import BingNewsProvider

_SAMPLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:News="https://www.bing.com/news/search?q=test&amp;format=RSS">
<channel>
  <title>test - BingNews</title>
  <link>https://www.bing.com/news/search?q=test&amp;format=RSS</link>
  <description>Search results</description>
  <item>
    <title>OpenAI announces new model release</title>
    <link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;aid=&amp;tid=abc&amp;url=https%3a%2f%2fexample.com%2fopenai-announcement&amp;c=1&amp;mkt=en-us</link>
    <description>OpenAI unveiled its latest model with improved reasoning capabilities.</description>
    <pubDate>Mon, 17 Aug 2026 23:34:00 GMT</pubDate>
    <News:Source>The Example Times</News:Source>
  </item>
  <item>
    <title>Weather forecast for the weekend</title>
    <link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;tid=def&amp;url=https%3a%2f%2fweather.example.org%2fweekend</link>
    <description>Sunny skies expected across most regions.</description>
    <pubDate>Tue, 18 Aug 2026 06:15:00 GMT</pubDate>
    <News:Source>Weather Daily</News:Source>
  </item>
  <item>
    <title>Direct link item</title>
    <link>https://direct.example.net/story</link>
    <description/>
  </item>
</channel>
</rss>
"""

_EMPTY_XML = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>empty - BingNews</title></channel></rss>
"""


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert BingNewsProvider().is_available() is True


def test_parse_basic() -> None:
    p = BingNewsProvider()
    result = p._parse(_SAMPLE_XML, limit=10)

    assert len(result.results) == 3
    r = result.results[0]
    assert r.title == "OpenAI announces new model release"
    assert r.url == "https://example.com/openai-announcement"
    assert (
        r.snippet
        == "OpenAI unveiled its latest model with improved reasoning capabilities."
    )
    assert r.source == "The Example Times"
    assert r.provider == "bing_news"
    assert r.rank == 1
    assert r.published_date == "2026-08-17"
    assert r.extra["outlet"] == "The Example Times"


def test_parse_decodes_article_url_from_redirect() -> None:
    p = BingNewsProvider()
    result = p._parse(_SAMPLE_XML, limit=10)
    r = result.results[1]
    # The redirect URL should be unwrapped to the real article URL.
    assert r.url == "https://weather.example.org/weekend"
    assert "apiclick.aspx" not in r.url


def test_parse_link_without_url_param_keeps_link() -> None:
    p = BingNewsProvider()
    result = p._parse(_SAMPLE_XML, limit=10)
    r = result.results[2]
    assert r.url == "https://direct.example.net/story"
    assert r.snippet == ""
    assert r.published_date is None


def test_parse_empty_feed() -> None:
    p = BingNewsProvider()
    result = p._parse(_EMPTY_XML, limit=10)
    assert result.results == []


def test_parse_respects_limit() -> None:
    p = BingNewsProvider()
    result = p._parse(_SAMPLE_XML, limit=1)
    assert len(result.results) == 1
    assert result.results[0].rank == 1


@pytest.mark.asyncio
async def test_search_hits_endpoint_and_parses(respx_mock) -> None:
    respx_mock.get("https://www.bing.com/news/search").mock(
        return_value=respx.MockResponse(200, text=_SAMPLE_XML),
    )

    p = BingNewsProvider()
    result = await p.search("test", SearchParams(num_results=5))

    assert len(result.results) == 3
    assert result.results[0].provider == "bing_news"


@pytest.mark.asyncio
async def test_search_sends_feed_params(respx_mock) -> None:
    route = respx_mock.get("https://www.bing.com/news/search").mock(
        return_value=respx.MockResponse(200, text=_SAMPLE_XML),
    )

    p = BingNewsProvider()
    await p.search("test", SearchParams(num_results=5))

    request = route.calls.last.request
    assert request.url.params["q"] == "test"
    assert request.url.params["format"] == "RSS"
    assert 'sortbydate="1"' in request.url.params["qft"]


@pytest.mark.asyncio
async def test_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get("https://www.bing.com/news/search").mock(
        return_value=respx.MockResponse(503),
    )

    p = BingNewsProvider()
    with pytest.raises(HTTPStatusError):
        await p.search("test", SearchParams(num_results=5))
