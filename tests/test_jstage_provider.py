"""Unit tests for the J-STAGE Japanese journal search provider."""

from __future__ import annotations

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.jstage import JStageProvider

_ENDPOINT = "https://api.jstage.jst.go.jp/searchapi/do"

# Realistic Atom feed with an English-provisioned entry and a Japanese-only one.
_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed  xmlns="http://www.w3.org/2005/Atom"
  xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/"
  xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
  xml:lang="ja" >
  <result>
    <status>WARN_002</status>
    <message>WARN_002</message>
  </result>
  <title>Articles</title>
  <servicecd>3</servicecd>
  <updated>2026-09-21T00:39+09:00</updated>
  <opensearch:totalResults>3126</opensearch:totalResults>
  <opensearch:startIndex>1</opensearch:startIndex>
  <opensearch:itemsPerPage>2</opensearch:itemsPerPage>
  <entry>
    <article_title>
      <en><![CDATA[Surround Inhibition Mechanism by Deep Learning]]></en>
      <ja><![CDATA[深層学習による周囲抑制機構]]></ja>
    </article_title>
    <article_link>
      <en>https://www.jstage.jst.go.jp/article/pjsai/JSAI2019/0/JSAI2019_2H3J201/_article</en>
      <ja>https://www.jstage.jst.go.jp/article/pjsai/JSAI2019/0/JSAI2019_2H3J201/_article/-char/ja/</ja>
    </article_link>
    <author>
      <en>
        <name><![CDATA[Mamoru SUGAMOTO]]></name>
        <name><![CDATA[Naoaki FUJIMOTO]]></name>
        <name><![CDATA[Muneharu ONOUE]]></name>
        <name><![CDATA[Tsukasa YUMIBAYASHI]]></name>
      </en>
      <ja><name><![CDATA[菅本 守]]></name></ja>
    </author>
    <cdjournal>pjsai</cdjournal>
    <material_title>
      <en><![CDATA[Proceedings of the Annual Conference of JSAI]]></en>
      <ja><![CDATA[人工知能学会全国大会論文集]]></ja>
    </material_title>
    <prism:issn>2433-328X</prism:issn>
    <prism:eIssn>2433-3298</prism:eIssn>
    <prism:volume>8</prism:volume>
    <prism:number>1</prism:number>
    <prism:startingPage>113</prism:startingPage>
    <prism:endingPage>120</prism:endingPage>
    <pubyear>2025</pubyear>
    <prism:doi>10.31662/jmaj.2024-0197</prism:doi>
    <systemcode>1</systemcode>
    <systemname>J-STAGE</systemname>
    <title><![CDATA[Surround Inhibition Mechanism by Deep Learning]]></title>
    <link href="https://www.jstage.jst.go.jp/article/pjsai/JSAI2019/0/JSAI2019_2H3J201/_article/-char/ja/"/>
    <id>https://www.jstage.jst.go.jp/article/pjsai/JSAI2019/0/JSAI2019_2H3J201/_article/-char/ja/</id>
    <updated>2025-02-07T09:00+09:00</updated>
  </entry>
  <entry>
    <article_title>
      <en/>
      <ja><![CDATA[深層学習の応用]]></ja>
    </article_title>
    <article_link>
      <en/>
      <ja/>
    </article_link>
    <author>
      <en/>
      <ja><name><![CDATA[松尾 豊]]></name></ja>
    </author>
    <cdjournal>ieiceissjournal</cdjournal>
    <material_title>
      <en/>
      <ja><![CDATA[情報・システムソサイエティ誌]]></ja>
    </material_title>
    <prism:issn>         </prism:issn>
    <prism:volume>19</prism:volume>
    <pubyear>2014</pubyear>
    <title><![CDATA[深層学習の応用]]></title>
    <link href="https://www.jstage.jst.go.jp/article/ieiceissjournal/19/1/19_12/_article/-char/ja/"/>
    <id>https://www.jstage.jst.go.jp/article/ieiceissjournal/19/1/19_12/_article/-char/ja/</id>
    <updated>2014-01-01T09:00+09:00</updated>
  </entry>
</feed>"""


def test_jstage_name_tags_and_availability() -> None:
    p = JStageProvider()
    assert p.name == "jstage"
    assert p.tags == ["academic", "web", "science"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_jstage_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "jstage" in registry
    assert registry["jstage"].tags == ["academic", "web", "science"]


def test_jstage_parse_english_entry() -> None:
    p = JStageProvider()
    result = p._parse(_FEED, limit=5)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Surround Inhibition Mechanism by Deep Learning"
    assert r.url == (
        "https://www.jstage.jst.go.jp/article/pjsai/JSAI2019/0/"
        "JSAI2019_2H3J201/_article"
    )
    assert r.source == "jstage.jst.go.jp"
    assert r.provider == "jstage"
    assert r.rank == 1
    assert r.published_date == "2025"
    assert r.snippet == (
        "Mamoru SUGAMOTO, Naoaki FUJIMOTO, Muneharu ONOUE et al. | "
        "Proceedings of the Annual Conference of JSAI | Vol. 8, No. 1 | "
        "pp. 113-120 | 2025"
    )
    assert r.extra["doi"] == "10.31662/jmaj.2024-0197"
    assert r.extra["authors"] == [
        "Mamoru SUGAMOTO",
        "Naoaki FUJIMOTO",
        "Muneharu ONOUE",
        "Tsukasa YUMIBAYASHI",
    ]
    assert r.extra["journal"] == "Proceedings of the Annual Conference of JSAI"
    assert r.extra["cdjournal"] == "pjsai"
    assert r.extra["issn"] == "2433-328X"
    assert r.extra["eissn"] == "2433-3298"
    assert r.extra["volume"] == "8"
    assert r.extra["number"] == "1"
    assert r.extra["pages"] == "113-120"
    assert r.extra["pubyear"] == 2025
    assert r.extra["system_name"] == "J-STAGE"
    assert r.extra["updated"] == "2025-02-07T09:00+09:00"
    assert r.extra["total_results"] == 3126


def test_jstage_parse_japanese_only_entry() -> None:
    p = JStageProvider()
    r = p._parse(_FEED).results[1]

    assert r.title == "深層学習の応用"
    assert r.rank == 2
    # No article_link or DOI, so the Atom <link> element is used.
    assert r.url == (
        "https://www.jstage.jst.go.jp/article/ieiceissjournal/19/1/"
        "19_12/_article/-char/ja/"
    )
    assert r.published_date == "2014"
    assert r.snippet == "松尾 豊 | 情報・システムソサイエティ誌 | Vol. 19 | 2014"
    assert r.extra["doi"] is None
    assert r.extra["authors"] == ["松尾 豊"]
    assert r.extra["journal"] == "情報・システムソサイエティ誌"
    assert r.extra["issn"] is None
    assert r.extra["eissn"] is None
    assert r.extra["number"] is None
    assert r.extra["pages"] is None
    assert r.extra["pubyear"] == 2014


def test_jstage_doi_url_fallback_and_search_page_fallback() -> None:
    p = JStageProvider()
    feed = """<feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <article_title><en>With DOI</en></article_title>
        <prism:doi xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/"
          >10.1234/abc</prism:doi>
      </entry>
      <entry>
        <article_title><en>Bare</en></article_title>
      </entry>
    </feed>"""
    results = p._parse(feed).results

    assert results[0].url == "https://doi.org/10.1234/abc"
    assert results[1].url == "https://www.jstage.jst.go.jp/"


def test_jstage_published_date_falls_back_to_timestamp() -> None:
    p = JStageProvider()
    feed = """<feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <article_title><en>No year</en></article_title>
        <updated>2020-05-04T09:00+09:00</updated>
      </entry>
      <entry><article_title><en>No dates</en></article_title></entry>
    </feed>"""
    results = p._parse(feed).results

    assert results[0].published_date == "2020-05-04"
    assert results[1].published_date is None


def test_jstage_parse_skips_entries_without_title() -> None:
    p = JStageProvider()
    feed = """<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><article_title><en/></article_title></entry>
      <entry><article_title><ja>深層学習</ja></article_title></entry>
    </feed>"""
    results = p._parse(feed).results

    assert [r.title for r in results] == ["深層学習"]
    assert results[0].rank == 1


def test_jstage_parse_respects_limit() -> None:
    p = JStageProvider()
    entries = "".join(
        f"<entry><article_title><en>paper{n}</en></article_title></entry>"
        for n in range(3)
    )
    feed = f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'

    assert len(p._parse(feed, limit=2).results) == 2
    assert len(p._parse(feed).results) == 3


def test_jstage_parse_error_status_yields_no_results() -> None:
    p = JStageProvider()
    feed = """<feed xmlns="http://www.w3.org/2005/Atom">
      <result><status>ERR_012</status><message>ERR_012</message></result>
      <entry><article_title><en>Should not appear</en></article_title></entry>
    </feed>"""

    assert p._parse(feed).results == []


def test_jstage_parse_empty_and_malformed() -> None:
    p = JStageProvider()
    assert p._parse("<feed xmlns='http://www.w3.org/2005/Atom'></feed>").results == []
    assert p._parse("not xml at all <<<").results == []
    assert p._parse("").results == []
    assert p._parse(None).results == []
    assert p._parse([1, 2, 3]).results == []
    # A WARN status (noisy full-text match) still yields its entries.
    warn = """<feed xmlns="http://www.w3.org/2005/Atom">
      <result><status>WARN_002</status></result>
      <entry><article_title><en>Kept</en></article_title></entry>
    </feed>"""
    assert [r.title for r in p._parse(warn).results] == ["Kept"]


def test_jstage_helpers() -> None:
    from metasearchmcp.providers.jstage import _clean, _int

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _clean(5) == ""

    assert _int("3126") == 3126
    assert _int(2014) == 2014
    assert _int(True) is None
    assert _int("abc") is None
    assert _int(None) is None


async def test_jstage_search_sends_expected_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, text=_FEED)
    )

    result = await JStageProvider().search(
        "  deep learning  ",
        SearchParams(num_results=7),
    )

    assert route.called
    params = route.calls[0].request.url.params
    assert params["service"] == "3"
    assert params["article"] == "deep learning"
    assert params["count"] == "7"
    assert params["start"] == "0"
    assert len(respx_mock.calls) == 1
    assert [r.title for r in result.results] == [
        "Surround Inhibition Mechanism by Deep Learning",
        "深層学習の応用",
    ]


async def test_jstage_search_caps_results_to_provider_limit(respx_mock) -> None:
    entries = "".join(
        f"<entry><article_title><en>paper{n}</en></article_title></entry>"
        for n in range(10)
    )
    feed = f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(200, text=feed))

    provider = JStageProvider()
    provider._max_results = 3
    result = await provider.search("paper", SearchParams(num_results=50))

    assert len(respx_mock.calls) == 1
    assert len(result.results) == 3
    assert respx_mock.calls[0].request.url.params["count"] == "3"


async def test_jstage_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT)

    result = await JStageProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_jstage_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(503))

    with pytest.raises(httpx.HTTPStatusError):
        await JStageProvider().search("deep learning", SearchParams())
