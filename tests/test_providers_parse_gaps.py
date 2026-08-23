"""Parse-level unit tests filling coverage gaps.

Covers providers that previously had no direct class-level unit tests:
Brave (parse), DuckDuckGo (parse), Yandex (parse), and Google (serpbase
related-searches filtering is covered in test_providers.py; here we cover
the Google HTML parse helpers).

These tests exercise only the pure ``_parse`` methods with fixture data,
so they never touch the network.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Brave
# ---------------------------------------------------------------------------


def _brave_response() -> dict:
    return {
        "web": {
            "results": [
                {
                    "title": "FastAPI - The Modern Python Web Framework",
                    "url": "https://fastapi.tiangolo.com/",
                    "description": (
                        "FastAPI is a modern, fast web framework for Python."
                    ),
                },
                {
                    "title": "FastAPI on GitHub",
                    "url": "https://github.com/fastapi/fastapi",
                    "description": "Source code and issue tracker.",
                },
            ],
        },
    }


def test_brave_parse_basic() -> None:
    from metasearchmcp.providers.brave import BraveProvider

    p = BraveProvider()
    result = p._parse(_brave_response())

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "FastAPI - The Modern Python Web Framework"
    assert r.url == "https://fastapi.tiangolo.com/"
    assert "modern, fast web framework" in r.snippet
    assert r.provider == "brave"
    assert r.rank == 1
    assert r.published_date is None


def test_brave_parse_ranks_and_empty() -> None:
    from metasearchmcp.providers.brave import BraveProvider

    p = BraveProvider()
    result = p._parse(_brave_response())
    assert result.results[1].rank == 2

    empty = p._parse({"web": {"results": []}})
    assert empty.results == []


# ---------------------------------------------------------------------------
# DuckDuckGo
# ---------------------------------------------------------------------------

_DDG_HTML = """
<html><body>
  <div class="result">
    <div class="result__title"><a href="https://example.com/page">Example Page</a></div>
    <a class="result__snippet">A snippet about the example page.</a>
  </div>
  <div class="result">
  <div class="result__title">
    <a href="https://html.duckduckgo.com/l/?uddg=https%3A%2F%2Ftarget.example.org%2Fpath&amp;rut=abc">Redirected</a>
  </div>
  <a class="result__snippet">A redirected result.</a>
  </div>
  <div class="result">
    <div class="result__title"><a href="">Empty href</a></div>
  </div>
</body></html>
"""


def test_duckduckgo_parse_basic() -> None:
    from metasearchmcp.providers.duckduckgo import DuckDuckGoProvider

    p = DuckDuckGoProvider()
    result = p._parse(_DDG_HTML)

    assert len(result.results) == 2  # empty-href item is skipped
    r = result.results[0]
    assert r.title == "Example Page"
    assert r.url == "https://example.com/page"
    assert "snippet about the example page" in r.snippet
    assert r.provider == "duckduckgo"
    assert r.rank == 1


def test_duckduckgo_parse_redirect_unwrapping() -> None:
    from metasearchmcp.providers.duckduckgo import DuckDuckGoProvider

    p = DuckDuckGoProvider()
    result = p._parse(_DDG_HTML)
    # The /l/ redirect wrapper must be unwrapped to the real target URL.
    assert result.results[1].url == "https://target.example.org/path"


def test_duckduckgo_parse_limit_and_empty() -> None:
    from metasearchmcp.providers.duckduckgo import DuckDuckGoProvider

    p = DuckDuckGoProvider()
    assert len(p._parse(_DDG_HTML, max_results=1).results) == 1
    assert p._parse("<html><body></body></html>").results == []


# ---------------------------------------------------------------------------
# Yandex
# ---------------------------------------------------------------------------

_YANDEX_HTML = """
<html><body>
  <ol>
    <li class="serp-item">
      <div class="organic">
        <h2>
          <a class="OrganicTitle-Link" href="https://example.com/yandex">
            Yandex Result
          </a>
        </h2>
        <div class="OrganicTextContentSpan">First organic result snippet.</div>
      </div>
    </li>
    <li class="serp-item">
      <div class="organic">
        <h2><a href="https://other.example.org/">Second Result</a></h2>
        <div class="Organic-ContentWrapper">Second result content.</div>
      </div>
    </li>
    <li class="serp-item">
      <div class="organic">
        <h2><a href="/relative/path">Skipped relative link</a></h2>
      </div>
    </li>
  </ol>
</body></html>
"""


def test_yandex_parse_basic() -> None:
    from metasearchmcp.providers.yandex import YandexProvider

    p = YandexProvider()
    result = p._parse(_YANDEX_HTML)

    assert len(result.results) == 2  # relative href is skipped
    r = result.results[0]
    assert r.title == "Yandex Result"
    assert r.url == "https://example.com/yandex"
    assert "First organic result" in r.snippet
    assert r.provider == "yandex"
    assert r.rank == 1


def test_yandex_parse_alternative_snippet_selector() -> None:
    from metasearchmcp.providers.yandex import YandexProvider

    p = YandexProvider()
    result = p._parse(_YANDEX_HTML)
    assert "Second result content" in result.results[1].snippet


def test_yandex_parse_limit_and_empty() -> None:
    from metasearchmcp.providers.yandex import YandexProvider

    p = YandexProvider()
    assert len(p._parse(_YANDEX_HTML, max_results=1).results) == 1
    assert p._parse("<html><body></body></html>").results == []


# ---------------------------------------------------------------------------
# Google (HTML helpers)
# ---------------------------------------------------------------------------


def _google_html() -> str:
    return """
<html><body>
  <div id="search">
    <div class="g">
      <h3><a href="https://example.com/one">Result One</a></h3>
      <div class="VwiC3b">First snippet text.</div>
    </div>
    <div class="g">
      <h3><a href="https://example.com/two">Result Two</a></h3>
      <div class="VwiC3b">Second snippet text.</div>
    </div>
  </div>
</body></html>
"""


def test_google_parse_basic() -> None:
    from metasearchmcp.providers.google import GoogleProvider

    p = GoogleProvider()
    result = p._parse(_google_html())

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Result One"
    assert r.url == "https://example.com/one"
    assert r.provider == "google"
    assert r.rank == 1


def test_google_parse_empty() -> None:
    from metasearchmcp.providers.google import GoogleProvider

    p = GoogleProvider()
    assert p._parse("<html><body></body></html>").results == []
