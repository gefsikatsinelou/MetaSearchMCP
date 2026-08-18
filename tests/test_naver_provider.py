"""Unit tests for the Naver web search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.naver import NaverProvider

# A minimal HTML fixture mirroring Naver's server-rendered result DOM:
# - advertisements live in "ad" / "bizsite" blocks and must be skipped
# - organic results are <li class="bx"> items with a link_tit anchor and
#   an api_txt_lines / total_dsc description container
_HTML = """
<html><body>
<ul class="lst_type">
  <li class="bx" data-ad="true">
    <a class="link_tit" href="https://ad.example.co.kr/shop">Sponsored mall</a>
    <div class="api_txt_lines">광고 상품 설명입니다.</div>
  </li>
  <li class="bx">
    <a class="link_tit" href="https://www.python.org/">Welcome to Python.org</a>
    <div class="api_txt_lines">The mission of the Python Software Foundation.</div>
  </li>
  <li class="bx">
    <a class="link_tit" href="https://python.or.kr/">파이썬 한국 사용자 모임</a>
    <div class="total_dsc">파이썬 프로그래밍 언어 관련 정보를 공유합니다.</div>
  </li>
  <li class="bizsite bx">
    <a class="link_tit" href="https://biz.example.co.kr/">Biz listing</a>
    <div class="total_dsc">기업 소개 페이지입니다.</div>
  </li>
</ul>
</body></html>
"""


def _provider() -> NaverProvider:
    return NaverProvider()


def test_parse_basic():
    p = _provider()
    result = p._parse(_HTML)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Welcome to Python.org"
    assert r.url == "https://www.python.org/"
    assert r.provider == "naver"
    assert r.rank == 1
    assert "mission of the Python Software" in r.snippet


def test_parse_skips_advertisements():
    p = _provider()
    result = p._parse(_HTML)

    urls = [r.url for r in result.results]
    assert "https://ad.example.co.kr/shop" not in urls
    assert "https://biz.example.co.kr/" not in urls
    assert all("example.co.kr" not in r.url for r in result.results)


def test_parse_limit():
    p = _provider()
    result = p._parse(_HTML, max_results=1)
    assert len(result.results) == 1
    assert result.results[0].title == "Welcome to Python.org"


def test_parse_empty():
    p = _provider()
    result = p._parse("<html><body></body></html>")
    assert result.results == []


def test_parse_tit_fallback_and_dedup():
    p = _provider()
    html = """
    <html><body><ul class="lst_type">
      <li class="bx">
        <a class="tit" href="https://m.python.org/">Mobile Python</a>
        <div class="total_dsc">Mobile-friendly Python docs.</div>
      </li>
      <li class="bx">
        <a class="tit" href="https://m.python.org/">Mobile Python dup</a>
        <div class="total_dsc">Duplicate URL should be skipped.</div>
      </li>
      <li class="bx">
        <a href="/relative">Relative link</a>
      </li>
    </ul></body></html>
    """
    result = p._parse(html)
    assert len(result.results) == 1
    assert result.results[0].title == "Mobile Python"


def test_is_available_follows_unstable_flag():
    from metasearchmcp.config import get_settings

    original = get_settings().allow_unstable_providers
    try:
        get_settings().allow_unstable_providers = False
        assert _provider().is_available() is False
        get_settings().allow_unstable_providers = True
        assert _provider().is_available() is True
    finally:
        get_settings().allow_unstable_providers = original


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock):
    import respx

    respx_mock.get(
        "https://search.naver.com/search.naver",
        params={"query": "python"},
    ).mock(
        return_value=respx.MockResponse(200, text=_HTML),
    )

    p = _provider()
    result = await p.search("python", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "naver"
    assert result.results[0].title == "Welcome to Python.org"
