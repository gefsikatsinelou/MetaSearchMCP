from __future__ import annotations


def test_startpage_extracts_sc_code():
    from metasearchmcp.providers.startpage import StartpageProvider

    html = """
    <form id="search" action="/sp/search" method="post">
      <input type="hidden" name="sc" value="abc123token" />
    </form>
    """

    assert StartpageProvider._extract_sc_code(html) == "abc123token"
