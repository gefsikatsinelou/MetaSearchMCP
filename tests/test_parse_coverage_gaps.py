"""Parse-level unit tests for Yahoo, Startpage, and Mojeek HTML parsers.

These providers previously only had tests for utility helpers or shared
generic tests; this module exercises their pure ``_parse`` methods with
fixture data so the parsing logic is covered without any network access.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Yahoo
# ---------------------------------------------------------------------------


def _yahoo_html() -> str:
    return """
    <div class="algo-sr">
      <div class="compTitle">
        <a href="https://r.search.yahoo.com/_ylt=abc/RU=https%3a%2f%2fexample.com%2fasyncio/RK=2/RS=xyz">
          <h3><span>Python asyncio guide</span></h3>
        </a>
      </div>
      <div class="compText">Learn asyncio from the official docs.</div>
    </div>
    <div class="algo-sr">
      <div class="compTitle">
        <h3><a href="https://plain.example.org/result">Plain result</a></h3>
      </div>
      <div class="compText">Second result snippet.</div>
    </div>
    <div class="algo-sr">
      <div class="compTitle">
        <a href="https://r.search.yahoo.com/_ylt=def/RU=https%3a%2f%2fexample.com%2fno-title/RK=1/RS=w"><h3><span></span></h3></a>
      </div>
      <div class="compText">No title result.</div>
    </div>
    <div class="AlsoTry">
      <table><tr><td><a>python async await</a></td></tr></table>
      <a>asyncio tutorial</a>
    </div>
    """


def test_yahoo_parse_basic() -> None:
    from metasearchmcp.providers.yahoo import YahooProvider

    p = YahooProvider()
    result = p._parse(_yahoo_html())

    # The third block has an empty title and is skipped.
    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Python asyncio guide"
    assert r.url == "https://example.com/asyncio"
    assert r.provider == "yahoo"
    assert r.rank == 1
    assert "official docs" in r.snippet


def test_yahoo_parse_ranks_and_plain_url() -> None:
    from metasearchmcp.providers.yahoo import YahooProvider

    p = YahooProvider()
    result = p._parse(_yahoo_html())

    assert result.results[1].rank == 2
    assert result.results[1].title == "Plain result"
    assert result.results[1].url == "https://plain.example.org/result"


def test_yahoo_parse_collects_suggestions() -> None:
    from metasearchmcp.providers.yahoo import YahooProvider

    p = YahooProvider()
    result = p._parse(_yahoo_html())

    assert result.suggestions == ["python async await", "asyncio tutorial"]


def test_yahoo_parse_limit_and_empty() -> None:
    from metasearchmcp.providers.yahoo import YahooProvider

    p = YahooProvider()
    assert len(p._parse(_yahoo_html(), max_results=1).results) == 1
    assert p._parse("<html><body></body></html>").results == []
    assert p._parse("<html><body></body></html>").suggestions == []


# ---------------------------------------------------------------------------
# Startpage
# ---------------------------------------------------------------------------


def _startpage_html() -> str:
    return """
    <html><body>
      <div class="result">
        <h2 class="wgl-title">
          <a class="result-title" href="https://example.com/one">Result One</a>
        </h2>
        <p class="description">First result description.</p>
      </div>
      <div class="result">
        <h2><a class="result-title" href="https://example.com/two">Result Two</a></h2>
      </div>
      <div class="result">
        <a href="/relative/path">Skipped relative link</a>
      </div>
      <div class="result">
        <a href="https://fallback.example.org/three">Fallback Title</a>
      </div>
    </body></html>
    """


def test_startpage_parse_basic() -> None:
    from metasearchmcp.providers.startpage import StartpageProvider

    p = StartpageProvider()
    result = p._parse(_startpage_html())

    # Relative-href block is skipped; the fallback-anchor block is kept.
    assert len(result.results) == 3
    r = result.results[0]
    assert r.title == "Result One"
    assert r.url == "https://example.com/one"
    assert r.snippet == "First result description."
    assert r.provider == "startpage"
    assert r.rank == 1


def test_startpage_parse_fallback_anchor() -> None:
    from metasearchmcp.providers.startpage import StartpageProvider

    p = StartpageProvider()
    result = p._parse(_startpage_html())

    assert result.results[2].title == "Fallback Title"
    assert result.results[2].url == "https://fallback.example.org/three"


def test_startpage_parse_limit_and_empty() -> None:
    from metasearchmcp.providers.startpage import StartpageProvider

    p = StartpageProvider()
    assert len(p._parse(_startpage_html(), max_results=2).results) == 2
    assert p._parse("<html><body></body></html>").results == []


# ---------------------------------------------------------------------------
# Mojeek
# ---------------------------------------------------------------------------


def _mojeek_html() -> str:
    return """
    <html><body>
      <ul class="results-standard">
        <li>
          <h2><a class="title" href="https://example.com/mojeek-one">Mojeek One</a></h2>
          <p class="s">Mojeek result one snippet.</p>
        </li>
        <li>
          <a class="title" href="https://example.com/mojeek-two">Mojeek Two</a>
        </li>
        <li>
          <a href="https://example.com/mojeek-three">Mojeek Three</a>
        </li>
        <li>
          <a href="/relative/path">Skipped relative link</a>
        </li>
      </ul>
    </body></html>
    """


def test_mojeek_parse_basic() -> None:
    from metasearchmcp.providers.mojeek import MojeekProvider

    p = MojeekProvider()
    result = p._parse(_mojeek_html())

    assert len(result.results) == 3  # relative-href item is skipped
    r = result.results[0]
    assert r.title == "Mojeek One"
    assert r.url == "https://example.com/mojeek-one"
    assert r.provider == "mojeek"
    assert r.rank == 1
    assert "snippet" in r.snippet


def test_mojeek_parse_anchor_fallbacks() -> None:
    from metasearchmcp.providers.mojeek import MojeekProvider

    p = MojeekProvider()
    result = p._parse(_mojeek_html())

    assert result.results[1].title == "Mojeek Two"
    assert result.results[2].title == "Mojeek Three"


def test_mojeek_parse_limit_and_empty() -> None:
    from metasearchmcp.providers.mojeek import MojeekProvider

    p = MojeekProvider()
    assert len(p._parse(_mojeek_html(), max_results=2).results) == 2
    assert p._parse("<html><body></body></html>").results == []
