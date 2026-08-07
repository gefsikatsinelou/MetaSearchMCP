"""Unit tests for the CourtListener legal search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.providers.courtlistener import CourtListenerProvider

_SAMPLE_RESPONSE = {
    "count": 2,
    "results": [
        {
            "caseName": "Aaron v. Supreme Court of Ohio",
            "absolute_url": "/opinion/10285124/aaron-v-supreme-court-of-ohio/",
            "citation": ["258 N.E.3d 687", "2024 Ohio 5616"],
            "court": "Ohio Court of Appeals",
            "court_citation_string": "Ohio Ct. App.",
            "docketNumber": "24AP-232",
            "judge": "Edelstein",
            "status": "Published",
            "neutralCite": "2024 Ohio 5616",
            "citeCount": 3,
            "dateFiled": "2024-11-26",
            "dateArgued": "2024-10-02",
            "opinions": [
                {
                    "download_url": "https://www.supremecourt.ohio.gov/rod/docs/pdf/10/2024/2024-Ohio-5616.pdf",
                    "snippet": "Filed 11/26/24",
                },
            ],
        },
        {
            "caseName": "No URL Case",
            "absolute_url": "",
            "court": "Some Court",
            "dateFiled": None,
            "citation": [],
        },
    ],
}

_EMPTY_RESPONSE = {"count": 0, "results": []}


def test_courtlistener_parse_basic():
    p = CourtListenerProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Aaron v. Supreme Court of Ohio"
    assert (
        r.url
        == "https://www.courtlistener.com/opinion/10285124/aaron-v-supreme-court-of-ohio/"
    )
    assert "258 N.E.3d 687; 2024 Ohio 5616" in r.snippet
    assert "Court: Ohio Court of Appeals" in r.snippet
    assert "Docket: 24AP-232" in r.snippet
    assert "Judge: Edelstein" in r.snippet
    assert "Status: Published" in r.snippet
    assert r.source == "courtlistener.com"
    assert r.provider == "courtlistener"
    assert r.rank == 1
    assert r.published_date == "2024-11-26"
    assert r.extra["court"] == "Ohio Court of Appeals"
    assert r.extra["docket_number"] == "24AP-232"
    assert r.extra["judge"] == "Edelstein"
    assert r.extra["status"] == "Published"
    assert r.extra["citations"] == ["258 N.E.3d 687", "2024 Ohio 5616"]
    assert r.extra["cite_count"] == 3
    assert r.extra["date_argued"] == "2024-10-02"
    assert (
        r.extra["download_url"]
        == "https://www.supremecourt.ohio.gov/rod/docs/pdf/10/2024/2024-Ohio-5616.pdf"
    )


def test_courtlistener_parse_skips_item_without_url_and_name():
    p = CourtListenerProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    # Second item has neither a case name nor a URL -> skipped.
    assert all(r.title for r in result.results)


def test_courtlistener_parse_empty():
    p = CourtListenerProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_courtlistener_parse_missing_keys():
    p = CourtListenerProvider()
    result = p._parse(
        {
            "results": [
                {
                    "caseName": "Lonely Case",
                    "absolute_url": "/opinion/1/lonely-case/",
                },
            ],
        },
    )
    r = result.results[0]
    assert r.snippet == ""
    assert r.published_date is None
    assert r.extra["court"] == ""
    assert r.extra["citations"] == []
    assert r.extra["cite_count"] == 0
    assert r.extra["download_url"] == ""


def test_courtlistener_parse_respects_limit():
    """The API ignores page_size, so results are truncated client-side."""
    data = {
        "results": [
            {"caseName": f"Case {i}", "absolute_url": f"/opinion/{i}/case-{i}/"}
            for i in range(1, 6)
        ],
    }
    p = CourtListenerProvider()
    result = p._parse(data, limit=2)
    assert len(result.results) == 2
    assert result.results[0].title == "Case 1"
    assert result.results[1].title == "Case 2"


def test_courtlistener_parse_limit_none_keeps_all():
    data = {
        "results": [
            {"caseName": f"Case {i}", "absolute_url": f"/opinion/{i}/case-{i}/"}
            for i in range(1, 4)
        ],
    }
    p = CourtListenerProvider()
    result = p._parse(data)
    assert len(result.results) == 3


def test_courtlistener_citation_label():
    assert CourtListenerProvider._citation_label(["A", "B"]) == "A; B"
    assert CourtListenerProvider._citation_label(["", "B"]) == "B"
    assert CourtListenerProvider._citation_label([]) == ""
    assert CourtListenerProvider._citation_label(None) == ""


def test_courtlistener_clean_text():
    assert CourtListenerProvider._clean_text("  a\n  b ") == "a b"
    assert CourtListenerProvider._clean_text("") == ""
    assert CourtListenerProvider._clean_text(None) == ""


def test_courtlistener_is_available():
    """Keyless provider is always available."""
    assert CourtListenerProvider().is_available() is True


@pytest.mark.asyncio
async def test_courtlistener_search_builds_query(respx_mock):
    """The search method hits the search endpoint and parses the response."""
    import respx

    respx_mock.get("https://www.courtlistener.com/api/rest/v4/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    from metasearchmcp.contracts import SearchParams

    p = CourtListenerProvider()
    result = await p.search("first amendment", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "courtlistener"
