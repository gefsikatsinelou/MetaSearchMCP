from __future__ import annotations


def _sample_html() -> str:
    return """
    <div class="algo-sr">
      <div class="compTitle">
        <a href="https://r.search.yahoo.com/_ylt=abc/RU=https%3a%2f%2fexample.com%2fasyncio/RK=2/RS=xyz">
          <h3><span>Python asyncio guide</span></h3>
        </a>
      </div>
      <div class="compText">Learn asyncio from the official docs.</div>
    </div>
    <div class="AlsoTry">
      <table><tr><td><a>python async await</a></td></tr></table>
    </div>
    """


def test_yahoo_parse():
    from metasearchmcp.providers.yahoo import YahooProvider

    provider = YahooProvider()
    result = provider._parse(_sample_html())

    assert len(result.results) == 1
    item = result.results[0]
    assert item.title == "Python asyncio guide"
    assert item.url == "https://example.com/asyncio"
    assert item.provider == "yahoo"
    assert "official docs" in item.snippet
    assert result.suggestions == ["python async await"]


def test_yahoo_builds_cookie():
    from metasearchmcp.providers.yahoo import YahooProvider

    cookie = YahooProvider._build_sb_cookie(language="en", safe_search=True)

    assert "vm=i" in cookie
    assert "vl=lang_en" in cookie
