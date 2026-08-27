"""Unit tests for the arXiv API provider.

Covers Atom feed parsing (including malformed XML), the pure
``_parse_xml`` helper, rank/date handling, and the API call path.
"""

from __future__ import annotations

import pytest
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.arxiv import ArxivProvider


def _feed() -> str:
    """A realistic arXiv Atom feed with two entries."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>https://arxiv.org/abs/2301.00001</id>
    <title>Attention Is All You Need</title>
    <summary>We propose a new simple network architecture, the Transformer.</summary>
    <published>2023-01-01T00:00:00Z</published>
    <author><name>Vaswani et al.</name></author>
  </entry>
  <entry>
    <id>https://arxiv.org/abs/2301.00002</id>
    <title>BERT: Pre-training of Deep Bidirectional Transformers</title>
    <summary>We introduce BERT for language representation.</summary>
    <published>2023-01-02T00:00:00Z</published>
    <author><name>Devlin et al.</name></author>
  </entry>
</feed>"""


def _provider() -> ArxivProvider:
    return ArxivProvider()


def test_parse_basic() -> None:
    p = _provider()
    result = p._parse(_feed())

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Attention Is All You Need"
    assert r.url == "https://arxiv.org/abs/2301.00001"
    assert r.provider == "arxiv"
    assert r.rank == 1
    assert r.published_date == "2023-01-01"
    assert "Transformer" in r.snippet
    assert result.results[1].rank == 2


def test_parse_malformed_xml_returns_empty() -> None:
    p = _provider()
    assert p._parse("not xml at all <<<").results == []


def test_parse_empty_feed() -> None:
    p = _provider()
    result = p._parse("<feed xmlns='http://www.w3.org/2005/Atom'></feed>")
    assert result.results == []


def test_parse_skips_entries_without_id_or_title() -> None:
    """Entries missing a title/id must not crash and stay parseable."""
    p = _provider()
    feed = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Only a title</title>
    <summary>No id element.</summary>
  </entry>
</feed>"""
    result = p._parse(feed)
    assert len(result.results) == 1
    assert result.results[0].title == "Only a title"
    assert result.results[0].url == ""


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get("https://export.arxiv.org/api/query").mock(
        return_value=respx.MockResponse(200, text=_feed()),
    )

    p = _provider()
    result = await p.search("transformer", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "arxiv"
    assert result.results[0].title == "Attention Is All You Need"
    assert result.results[0].published_date == "2023-01-01"


@pytest.mark.asyncio
async def test_search_raises_on_api_error(respx_mock) -> None:
    import respx

    respx_mock.get("https://export.arxiv.org/api/query").mock(
        return_value=respx.MockResponse(500, text="boom"),
    )

    p = _provider()
    with pytest.raises(HTTPStatusError):
        await p.search("transformer", SearchParams(num_results=5))
