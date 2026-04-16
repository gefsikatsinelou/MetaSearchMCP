from __future__ import annotations


def _lite_html() -> str:
    return """
    <section>
      <article>
        <h2><a>Python asyncio docs</a></h2>
        <span class="url partner">docs.python.org/3/library/asyncio.html</span>
        <p>Official asyncio documentation.</p>
      </article>
    </section>
    """


def test_qwant_parse_lite():
    from metasearchmcp.providers.qwant import QwantProvider

    provider = QwantProvider()
    result = provider._parse_lite(_lite_html())

    assert len(result.results) == 1
    item = result.results[0]
    assert item.title == "Python asyncio docs"
    assert item.url == "https://docs.python.org/3/library/asyncio.html"
    assert item.provider == "qwant"
