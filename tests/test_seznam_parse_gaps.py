"""Parse-level unit tests for the Seznam.cz search provider.

Complements ``tests/test_seznam_provider.py`` (which covers the basic DOM
fixture) by exercising the parser's *robustness* branches: sponsored-block
detection, the multi-anchor result-block walk, deduplication, and the
non-HTTP anchor filter — all through the pure ``_parse`` method with no
network access.
"""

from __future__ import annotations

from metasearchmcp.providers.seznam import SeznamProvider


def _sponsored_html() -> str:
    """A page whose only organic heading sits inside a sponsored block.

    The label appears two levels above the heading (inside the sponsored
    container), which is within the three-step ancestor walk.
    """
    return """
    <html><body>
      <div>
        <div class="sponsored">
          <h3>Sponzorované výsledky</h3>
          <div>
            <h3><a data-e-a="heading" href="https://ads.example.cz/offer">
              Placená nabídka</a></h3>
            <div>Reklamní text.</div>
          </div>
        </div>
      </div>
    </body></html>
    """


def _nested_blocks_html() -> str:
    """A page whose results sit in nested divs (deep block walk)."""
    return """
    <html><body>
      <div class="wrap">
        <div class="inner">
          <div class="result">
            <h3><a data-e-a="heading" href="https://example.com/deep">
              Deep result</a></h3>
            <div>Deep snippet text.</div>
          </div>
        </div>
      </div>
    </body></html>
    """


def test_parse_flags_sponsored_result() -> None:
    p = SeznamProvider()
    result = p._parse(_sponsored_html())

    assert len(result.results) == 1
    r = result.results[0]
    assert r.extra.get("sponsored") is True
    assert r.title == "Placená nabídka"


def test_parse_organic_result_not_sponsored() -> None:
    p = SeznamProvider()
    result = p._parse(_nested_blocks_html())

    assert len(result.results) == 1
    r = result.results[0]
    assert r.extra.get("sponsored", False) is False
    assert r.title == "Deep result"
    assert r.url == "https://example.com/deep"


def test_parse_deep_block_snippet_extraction() -> None:
    p = SeznamProvider()
    result = p._parse(_nested_blocks_html())

    assert "Deep snippet text." in result.results[0].snippet


def test_parse_deduplicates_repeated_urls() -> None:
    p = SeznamProvider()
    html = """
    <html><body>
      <div>
        <h3><a data-e-a="heading" href="https://dup.example/">First</a></h3>
      </div>
      <div>
        <h3><a data-e-a="heading" href="https://dup.example/">Second</a></h3>
      </div>
    </body></html>
    """
    result = p._parse(html)

    assert len(result.results) == 1
    assert result.results[0].title == "First"


def test_parse_skips_non_http_anchors() -> None:
    p = SeznamProvider()
    html = """
    <html><body>
      <div>
        <h3><a data-e-a="heading" href="mailto:user@example.com">Mail</a></h3>
        <h3><a data-e-a="heading" href="/relative/path">Relative</a></h3>
        <h3><a data-e-a="heading" href="https://ok.example/">OK</a></h3>
      </div>
    </body></html>
    """
    result = p._parse(html)

    assert [r.url for r in result.results] == ["https://ok.example/"]
