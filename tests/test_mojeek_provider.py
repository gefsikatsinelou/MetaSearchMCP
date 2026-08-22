"""Unit tests for the Mojeek web search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.mojeek import MojeekProvider

_SAMPLE_HTML = """<!DOCTYPE html>
<html>
<head><title>Mojeek</title></head>
<body>
<ul class="results-standard">
  <li>
    <a class="title" href="https://example.com/page">Example Page</a>
    <p class="s">A description of the example page.</p>
  </li>
  <li>
    <a class="title" href="https://another.org/article">Another Article</a>
    <p class="s">Some more content here.</p>
  </li>
  <li>
    <a href="https://third.io/post">No snippet result</a>
  </li>
</ul>
</body>
</html>
"""

_EMPTY_HTML = """<!DOCTYPE html>
<html><body><ul class="results-standard"></ul></body></html>
"""


def test_mojeek_name_and_tags():
    p = MojeekProvider()
    assert p.name == "mojeek"
    assert p.tags == ["web", "privacy"]


def test_mojeek_parse_basic():
    p = MojeekProvider()
    result = p._parse(_SAMPLE_HTML)

    assert len(result.results) == 3
    r = result.results[0]
    assert r.title == "Example Page"
    assert r.url == "https://example.com/page"
    assert r.snippet == "A description of the example page."
    assert r.provider == "mojeek"
    assert r.rank == 1
    assert r.source == "example.com"


def test_mojeek_parse_ranks():
    p = MojeekProvider()
    result = p._parse(_SAMPLE_HTML)
    assert [r.rank for r in result.results] == [1, 2, 3]


def test_mojeek_parse_no_snippet():
    p = MojeekProvider()
    result = p._parse(_SAMPLE_HTML)
    assert result.results[2].snippet == ""


def test_mojeek_parse_respects_limit():
    p = MojeekProvider()
    result = p._parse(_SAMPLE_HTML, max_results=2)
    assert len(result.results) == 2


def test_mojeek_parse_empty():
    p = MojeekProvider()
    result = p._parse(_EMPTY_HTML)
    assert result.results == []


def test_mojeek_parse_skips_non_http_links():
    p = MojeekProvider()
    html = """
    <html><body><ul class="results-standard">
      <li><a class="title" href="/relative/path">Relative Link</a></li>
      <li><a class="title" href="javascript:void(0)">JS Link</a></li>
    </ul></body></html>
    """
    result = p._parse(html)
    assert result.results == []


@pytest.mark.asyncio
async def test_mojeek_search_hits_api_and_parses(respx_mock):
    """The search method fetches HTML and parses it into results."""
    import respx

    respx_mock.get("https://www.mojeek.com/search").mock(
        return_value=respx.MockResponse(200, text=_SAMPLE_HTML),
    )
    p = MojeekProvider()
    result = await p.search("example", SearchParams(num_results=5))

    assert len(result.results) == 3
    r = result.results[0]
    assert r.title == "Example Page"
    assert r.provider == "mojeek"


@pytest.mark.asyncio
async def test_mojeek_search_forwards_params(respx_mock):
    """Query, result count and language are forwarded as query parameters."""
    import respx

    route = respx_mock.get("https://www.mojeek.com/search").mock(
        return_value=respx.MockResponse(200, text=_EMPTY_HTML),
    )
    p = MojeekProvider()
    await p.search("hello world", SearchParams(num_results=7, language="fr"))

    request = route.calls.last.request
    assert request.url.params["q"] == "hello world"
    assert request.url.params["s"] == "7"
    assert request.url.params["lb"] == "fr"
