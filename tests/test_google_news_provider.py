"""Unit tests for the Google News RSS provider."""

# Long XML fixture lines are intentional; keep them readable as-is.
# ruff: noqa: E501

from __future__ import annotations

import pytest

from metasearchmcp.providers.google_news import GoogleNewsProvider

_SAMPLE_RSS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">\n'
    "<channel>\n"
    '  <title>"bitcoin" - Google News</title>\n'
    "  <link>https://news.google.com/search?q=bitcoin&amp;hl=en-US&amp;gl=US&amp;ceid=US:en</link>\n"
    "  <item>\n"
    "    <title>Bitcoin price rises above $70,000 - CoinDesk</title>\n"
    "    <link>https://news.google.com/rss/articles/CBMi1gFBitcoinA?oc=5</link>\n"
    '    <guid isPermaLink="false">CBMi1gFBitcoinA</guid>\n'
    "    <pubDate>Tue, 04 Aug 2026 23:40:29 GMT</pubDate>\n"
    '    <description>&lt;a href="https://news.google.com/rss/articles/CBMi1gFBitcoinA?oc=5" '
    'target="_blank"&gt;Bitcoin price rises above $70,000&lt;/a&gt;&amp;nbsp;&amp;nbsp;&lt;font '
    'color="#6f6f6f"&gt;CoinDesk&lt;/font&gt;</description>\n'
    '    <source url="https://www.coindesk.com">CoinDesk</source>\n'
    "  </item>\n"
    "  <item>\n"
    "    <title>Regulators weigh new crypto rules - Fox Business</title>\n"
    "    <link>https://news.google.com/rss/articles/CBMiqgFBitcoinB?oc=5</link>\n"
    '    <guid isPermaLink="false">CBMiqgFBitcoinB</guid>\n'
    "    <pubDate>Mon, 03 Aug 2026 00:42:00 GMT</pubDate>\n"
    '    <description>&lt;a href="https://news.google.com/rss/articles/CBMiqgFBitcoinB?oc=5" '
    'target="_blank"&gt;Regulators weigh new crypto rules&lt;/a&gt;&amp;nbsp;&amp;nbsp;&lt;font '
    'color="#6f6f6f"&gt;Fox Business&lt;/font&gt;</description>\n'
    '    <source url="https://www.foxbusiness.com">Fox Business</source>\n'
    "  </item>\n"
    "  <item>\n"
    "    <title>Markets digest weekly volatility - The Wall Street Journal</title>\n"
    "    <link>https://news.google.com/rss/articles/CBMiExample?oc=5</link>\n"
    '    <guid isPermaLink="false">CBMiExample</guid>\n'
    "    <pubDate>Sun, 02 Aug 2026 10:15:00 GMT</pubDate>\n"
    '    <description>&lt;a href="https://news.google.com/rss/articles/CBMiExample?oc=5" '
    'target="_blank"&gt;Markets digest weekly volatility&lt;/a&gt;&amp;nbsp;&amp;nbsp;&lt;font '
    'color="#6f6f6f"&gt;The Wall Street Journal&lt;/font&gt;</description>\n'
    "  </item>\n"
    "</channel>\n"
    "</rss>\n"
)

# An item whose description is missing the <font> source marker.
_SAMPLE_RSS_NO_DESC_SOURCE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<rss version="2.0">\n'
    "<channel>\n"
    "  <title>test</title>\n"
    "  <item>\n"
    "    <title>Headline only</title>\n"
    "    <link>https://news.google.com/rss/articles/CBMiNoSource?oc=5</link>\n"
    "    <pubDate>Sat, 01 Aug 2026 08:00:00 GMT</pubDate>\n"
    "    <description>Plain text description without an anchor.</description>\n"
    "  </item>\n"
    "</channel>\n"
    "</rss>\n"
)

_EMPTY_RSS = (
    '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title></channel></rss>'
)


def test_google_news_parse_basic():
    p = GoogleNewsProvider()
    result = p._parse(_SAMPLE_RSS, limit=10)

    assert len(result.results) == 3
    r = result.results[0]
    # The trailing " - CoinDesk" suffix is stripped from the title.
    assert r.title == "Bitcoin price rises above $70,000"
    assert r.url == "https://news.google.com/rss/articles/CBMi1gFBitcoinA?oc=5"
    assert "Bitcoin price rises above $70,000" in r.snippet
    assert r.source == "CoinDesk"
    assert r.provider == "google_news"
    assert r.rank == 1
    assert r.published_date == "2026-08-04"
    assert r.extra["outlet"] == "CoinDesk"
    assert r.extra["outlet_url"] == "https://www.coindesk.com"


def test_google_news_parse_source_from_font():
    """When the <source> element is absent, the <font> tag supplies it."""
    p = GoogleNewsProvider()
    result = p._parse(_SAMPLE_RSS, limit=10)
    r = result.results[2]

    assert r.source == "The Wall Street Journal"
    assert r.title == "Markets digest weekly volatility"
    assert r.extra["outlet"] == "The Wall Street Journal"
    assert r.extra["outlet_url"] == ""


def test_google_news_parse_no_description_source():
    p = GoogleNewsProvider()
    result = p._parse(_SAMPLE_RSS_NO_DESC_SOURCE, limit=10)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Headline only"
    assert r.source == "news.google.com"
    assert r.snippet == "Plain text description without an anchor."
    assert r.published_date == "2026-08-01"


def test_google_news_parse_limit():
    p = GoogleNewsProvider()
    result = p._parse(_SAMPLE_RSS, limit=2)
    assert len(result.results) == 2
    assert result.results[0].rank == 1
    assert result.results[1].rank == 2


def test_google_news_parse_empty_feed():
    p = GoogleNewsProvider()
    result = p._parse(_EMPTY_RSS, limit=10)
    assert result.results == []


def test_google_news_parse_pub_date_invalid():
    p = GoogleNewsProvider()
    assert p._parse_pub_date("not a date") is None
    assert p._parse_pub_date("") is None
    assert p._parse_pub_date(None) is None
    assert p._parse_pub_date("Tue, 04 Aug 2026 23:40:29 GMT") == "2026-08-04"


def test_google_news_clean_title():
    assert (
        GoogleNewsProvider._clean_title("Bitcoin rally - Reuters", "Reuters")
        == "Bitcoin rally"
    )
    assert (
        GoogleNewsProvider._clean_title("Bitcoin rally - Reuters", "")
        == "Bitcoin rally - Reuters"
    )
    assert GoogleNewsProvider._clean_title("  Spaced  ", "") == "Spaced"


def test_google_news_parse_description():
    p = GoogleNewsProvider()
    snippet, source = p._parse_description(
        '<a href="https://x.com" target="_blank">Headline</a>'
        '&nbsp;&nbsp;<font color="#6f6f6f">Reuters</font>',
    )
    assert "Headline" in snippet
    assert source == "Reuters"

    snippet, source = p._parse_description("")
    assert snippet == ""
    assert source == ""


@pytest.mark.asyncio
async def test_google_news_search_builds_query(respx_mock):
    """The search method hits the RSS endpoint and parses the response."""
    import respx

    respx_mock.get("https://news.google.com/rss/search").mock(
        return_value=respx.MockResponse(200, text=_SAMPLE_RSS),
    )

    from metasearchmcp.contracts import SearchParams

    p = GoogleNewsProvider()
    result = await p.search("bitcoin", SearchParams(num_results=5))

    assert len(result.results) == 3
    assert result.results[0].provider == "google_news"
