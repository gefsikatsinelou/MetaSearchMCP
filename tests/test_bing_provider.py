"""Tests for the Bing provider RSS parser."""

from __future__ import annotations


def _bing_rss() -> str:
    return """<?xml version='1.0' encoding='utf-8'?>
<rss version="2.0">
  <channel>
    <item>
      <title>Introducing GPT-4.1 in the API - OpenAI</title>
      <link>https://openai.com/index/gpt-4-1/</link>
      <description>OpenAI announces the GPT-4.1 model family.</description>
      <pubDate>Sun, 12 Apr 2026 03:25:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""


def test_bing_parse_rss():
    from metasearchmcp.providers.bing import BingProvider

    provider = BingProvider()
    result = provider._parse(_bing_rss())

    assert len(result.results) == 1
    item = result.results[0]
    assert item.title == "Introducing GPT-4.1 in the API - OpenAI"
    assert item.url == "https://openai.com/index/gpt-4-1/"
    assert item.provider == "bing"
    assert item.published_date == "2026-04-12"
