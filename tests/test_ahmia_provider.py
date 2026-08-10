"""Unit tests for the Ahmia Tor hidden services search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.ahmia import AhmiaProvider

_HOME_HTML = """
<!doctype html>
<html><body>
  <form id="searchForm" class="autocomplete" action="/search/" method="get">
    <input id="id_q" type="search" name="q" title="q">
    <input type="hidden" name="631f00" value="05e7e7">
    <input type="submit" value="Search">
  </form>
</body></html>
"""

_HREF_1 = (
    "/search/redirect?search_term=python&amp;"
    "redirect_url=http%3A%2F%2Ffoundry.onion%2Fpy"
)
_HREF_2 = (
    "/search/redirect?search_term=python&amp;"
    "redirect_url=https%3A%2F%2Freycd.onion%2Ftags%2FPython%2F"
)

_RESULTS_HTML = f"""
<html><body>
  <ol class="searchResults">
    <li class="result">
      <h4>
        <a href="{_HREF_1}">
          mirrors/python-nbxmpp: XMPP Python library
        </a>
      </h4>
      <p>python-nbxmpp - XMPP Python library</p>
      <cite>foundry.onion</cite>
    </li>
    <li class="result">
      <h4>
        <a href="{_HREF_2}">
          Tags: Python
        </a>
      </h4>
      <p>A tag index page for Python content.</p>
      <cite>reycd.onion</cite>
    </li>
    <li class="result">
      <h4><a href="https://example.com/direct">Direct link</a></h4>
      <p>No redirect wrapper.</p>
    </li>
    <li class="result">
      <h4><a href="/search/redirect?search_term=python">Missing redirect</a></h4>
    </li>
  </ol>
</body></html>
"""


def _provider() -> AhmiaProvider:
    return AhmiaProvider()


def test_extract_token() -> None:
    token = _provider()._extract_token(_HOME_HTML)
    assert token == ("631f00", "05e7e7")


def test_extract_token_missing_form() -> None:
    assert _provider()._extract_token("<html><body></body></html>") is None


def test_extract_token_missing_hidden_input() -> None:
    html = '<form id="searchForm"><input name="q"></form>'
    assert _provider()._extract_token(html) is None


def test_parse_basic() -> None:
    p = _provider()
    result = p._parse(_RESULTS_HTML)

    assert len(result.results) == 3  # missing-redirect item is skipped
    r = result.results[0]
    assert r.title == "mirrors/python-nbxmpp: XMPP Python library"
    assert r.url == "http://foundry.onion/py"
    assert r.provider == "ahmia"
    assert r.source == "ahmia.fi"
    assert r.rank == 1
    assert "XMPP Python library" in r.snippet
    assert r.extra["domain"] == "foundry.onion"


def test_parse_second_result_and_direct_link() -> None:
    p = _provider()
    result = p._parse(_RESULTS_HTML)

    assert result.results[1].url == "https://reycd.onion/tags/Python/"
    assert result.results[1].rank == 2
    # Non-redirect href is kept as-is.
    assert result.results[2].url == "https://example.com/direct"


def test_parse_limit() -> None:
    result = _provider()._parse(_RESULTS_HTML, max_results=2)
    assert len(result.results) == 2


def test_parse_empty() -> None:
    result = _provider()._parse("<html><body></body></html>")
    assert result.results == []


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_homepage_then_search(respx_mock) -> None:
    import respx

    respx_mock.get("https://ahmia.fi/").mock(
        return_value=respx.MockResponse(200, text=_HOME_HTML),
    )
    respx_mock.get(
        "https://ahmia.fi/search/",
        params={"q": "python", "631f00": "05e7e7"},
    ).mock(
        return_value=respx.MockResponse(200, text=_RESULTS_HTML),
    )

    p = _provider()
    result = await p.search("python", SearchParams(num_results=5))

    assert len(result.results) == 3
    assert result.results[0].provider == "ahmia"
    assert result.results[0].url == "http://foundry.onion/py"


@pytest.mark.asyncio
async def test_search_returns_empty_when_token_missing(respx_mock) -> None:
    import respx

    respx_mock.get("https://ahmia.fi/").mock(
        return_value=respx.MockResponse(200, text="<html><body></body></html>"),
    )

    p = _provider()
    result = await p.search("python", SearchParams(num_results=5))

    assert result.results == []
