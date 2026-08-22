"""Unit tests for the Ecosia web search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.ecosia import EcosiaProvider

_SAMPLE_HTML = """<!DOCTYPE html>
<html>
<head><title>Ecosia</title></head>
<body>
<main>
  <article class="result">
    <a class="result-title" href="https://example.com/page">Example Page</a>
    <p class="result-snippet">A description of the example page.</p>
  </article>
  <article class="result">
    <a class="result-title" href="https://another.org/article">Another Article</a>
    <p class="result-snippet">Some more content here.</p>
  </article>
  <article class="result">
    <a class="result-title" href="https://third.io/post">No snippet result</a>
  </article>
</main>
</body>
</html>
"""

_EMPTY_HTML = """<!DOCTYPE html>
<html><body><main><article class="result"></article></main></body></html>
"""


def test_ecosia_name_and_tags():
    p = EcosiaProvider()
    assert p.name == "ecosia"
    assert p.tags == ["web", "privacy"]


def test_ecosia_parse_basic():
    p = EcosiaProvider()
    result = p._parse(_SAMPLE_HTML)

    assert len(result.results) == 3
    r = result.results[0]
    assert r.title == "Example Page"
    assert r.url == "https://example.com/page"
    assert r.snippet == "A description of the example page."
    assert r.provider == "ecosia"
    assert r.rank == 1
    assert r.source == "example.com"


def test_ecosia_parse_ranks():
    p = EcosiaProvider()
    result = p._parse(_SAMPLE_HTML)
    assert [r.rank for r in result.results] == [1, 2, 3]


def test_ecosia_parse_no_snippet():
    p = EcosiaProvider()
    result = p._parse(_SAMPLE_HTML)
    assert result.results[2].snippet == ""


def test_ecosia_parse_respects_limit():
    p = EcosiaProvider()
    result = p._parse(_SAMPLE_HTML, max_results=2)
    assert len(result.results) == 2


def test_ecosia_parse_empty():
    p = EcosiaProvider()
    result = p._parse(_EMPTY_HTML)
    assert result.results == []


def test_ecosia_parse_fallback_anchor():
    """Results without a .result-title anchor fall back to the first http link."""
    p = EcosiaProvider()
    html = """
    <html><body><main>
      <article class="result">
        <h2><a href="https://fallback.example.org">Fallback Title</a></h2>
        <p class="result-snippet">Fallback snippet.</p>
      </article>
    </main></body></html>
    """
    result = p._parse(html)
    assert len(result.results) == 1
    assert result.results[0].title == "Fallback Title"
    assert result.results[0].url == "https://fallback.example.org"


@pytest.mark.asyncio
async def test_ecosia_search_hits_api_and_parses(respx_mock):
    """The search method fetches HTML and parses it into results."""
    import respx

    respx_mock.get("https://www.ecosia.org/search").mock(
        return_value=respx.MockResponse(200, text=_SAMPLE_HTML),
    )
    p = EcosiaProvider()
    result = await p.search("example", SearchParams(num_results=5))

    assert len(result.results) == 3
    r = result.results[0]
    assert r.title == "Example Page"
    assert r.provider == "ecosia"


@pytest.mark.asyncio
async def test_ecosia_search_forwards_params(respx_mock):
    """Query and language are forwarded as query parameters."""
    import respx

    route = respx_mock.get("https://www.ecosia.org/search").mock(
        return_value=respx.MockResponse(200, text=_EMPTY_HTML),
    )
    p = EcosiaProvider()
    await p.search("hello", SearchParams(num_results=4, language="de"))

    request = route.calls.last.request
    assert request.url.params["q"] == "hello"
    assert request.url.params["lang"] == "de"
