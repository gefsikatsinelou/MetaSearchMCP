"""Tests for the Startpage provider utilities."""

from __future__ import annotations


def test_startpage_extracts_sc_code():
    from metasearchmcp.providers.startpage import StartpageProvider

    html = """
    <form id="search" action="/sp/search" method="post">
      <input type="hidden" name="sc" value="abc123token" />
    </form>
    """

    assert StartpageProvider._extract_sc_code(html) == "abc123token"


def test_startpage_builds_normalized_locale_settings():
    from metasearchmcp.contracts import SearchParams
    from metasearchmcp.providers.startpage import StartpageProvider

    language, region = StartpageProvider._build_locale_settings(
        SearchParams(language="pt-BR", country=" pt-BR "),
    )

    assert language == "pt"
    assert region == "br-pt"
