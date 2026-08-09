"""Unit tests for the Seznam.cz search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.seznam import SeznamProvider

# A minimal HTML fixture mirroring Seznam's server-rendered result DOM:
# - sponsored results live under a block labelled "Sponzorované výsledky"
#   (label two levels above the sponsored heading, inside its own container)
# - organic results are anchors with data-e-a="heading" inside per-result divs
# - the shared "Layout--left" column wraps everything, so the label is four
#   levels above organic headings (outside the sponsored-detection walk)
_HTML = """
<html><body>
<div class="Layout--left">
  <div>
    <div>
      <h3>Sponzorované výsledky</h3>
      <div>
        <h3><a data-e-a="heading" href="https://ads.example.cz/kurz">
          Placený kurz programování</a></h3>
        <div>Reklamní popisek nabízející placený kurz.</div>
      </div>
    </div>
  </div>
  <div>
    <div>
      <h3><a data-e-a="heading" href="https://python.cz/">Python v ČR</a></h3>
      <div>Python je moderní programovací jazyk. Je univerzální.</div>
    </div>
    <div>
      <h3><a data-e-a="heading" href="https://www.python.org/">
        Welcome to Python.org</a></h3>
      <div>The mission of the Python Software Foundation is to promote.</div>
    </div>
  </div>
</div>
</body></html>
"""


def _provider() -> SeznamProvider:
    return SeznamProvider()


def test_parse_basic():
    p = _provider()
    result = p._parse(_HTML)

    assert len(result.results) == 3
    r = result.results[0]
    assert r.title == "Placený kurz programování"
    assert r.url == "https://ads.example.cz/kurz"
    assert r.provider == "seznam"
    assert r.rank == 1
    assert r.extra["sponsored"] is True


def test_parse_organic_results_not_sponsored():
    p = _provider()
    result = p._parse(_HTML)

    organic = [r for r in result.results if not r.extra.get("sponsored")]
    assert len(organic) == 2
    assert organic[0].title == "Python v ČR"
    assert organic[0].url == "https://python.cz/"
    assert "moderní programovací jazyk" in organic[0].snippet
    assert organic[1].rank == 3


def test_parse_limit():
    p = _provider()
    result = p._parse(_HTML, max_results=2)
    assert len(result.results) == 2


def test_parse_empty():
    p = _provider()
    result = p._parse("<html><body></body></html>")
    assert result.results == []


def test_parse_skips_non_http_and_duplicate_urls():
    p = _provider()
    html = """
    <html><body>
      <div>
        <h3><a data-e-a="heading" href="/relative">Relative link</a></h3>
      </div>
      <div>
        <h3><a data-e-a="heading" href="https://dup.example/">Dup</a></h3>
      </div>
      <div>
        <h3><a data-e-a="heading" href="https://dup.example/">Dup again</a></h3>
      </div>
    </div>
    </body></html>
    """
    result = p._parse(html)
    assert len(result.results) == 1
    assert result.results[0].title == "Dup"


def test_is_available():
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock):
    import respx

    respx_mock.get(
        "https://search.seznam.cz/",
        params={"q": "python"},
    ).mock(
        return_value=respx.MockResponse(200, text=_HTML),
    )

    p = _provider()
    result = await p.search("python", SearchParams(num_results=5))

    assert len(result.results) == 3
    assert result.results[0].provider == "seznam"
    assert result.results[0].title == "Placený kurz programování"
