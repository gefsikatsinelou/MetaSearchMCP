"""Unit tests for the SEC EDGAR provider (sec_edgar)."""

from __future__ import annotations

import pytest

from metasearchmcp.providers.sec_edgar import SecEdgarProvider

# ---------------------------------------------------------------------------
# Full-text search (FTS) parsing
# ---------------------------------------------------------------------------


def _fts_response() -> dict:
    return {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "ciks": ["0000320193"],
                        "display_names": ["Apple Inc.  (AAPL)  (CIK 0000320193)"],
                        "form": "10-K",
                        "adsh": "0000320193-26-000020",
                        "file_date": "2026-07-31",
                        "period_ending": "2026-06-27",
                        "file_type": "10-K",
                        "biz_locations": ["Cupertino, CA"],
                        "primary_document": "aapl-20260627.htm",
                        "core_type": "10-K",
                        "items": ["102"],
                    },
                },
                {
                    "_source": {
                        "ciks": ["0001318605"],
                        "display_names": ["Tesla, Inc.  (TSLA)  (CIK 0001318605)"],
                        "form": "10-Q",
                        "adsh": "0001318605-26-000045",
                        "file_date": "2026-08-01",
                        "period_ending": "2026-06-30",
                        "file_type": "10-Q",
                    },
                },
                # Exhibit documents must be skipped.
                {
                    "_source": {
                        "ciks": ["0000320193"],
                        "display_names": ["Apple Inc.  (AAPL)  (CIK 0000320193)"],
                        "form": "EX-31",
                        "adsh": "0000320193-26-000021",
                        "file_date": "2026-07-31",
                        "file_type": "EX-31",
                    },
                },
                # Missing CIK/display name -> skipped.
                {
                    "_source": {
                        "form": "8-K",
                        "adsh": "0000320193-26-000022",
                        "file_date": "2026-08-01",
                        "file_type": "8-K",
                    },
                },
                # Missing accession number -> skipped.
                {
                    "_source": {
                        "ciks": ["0000320193"],
                        "display_names": ["Apple Inc.  (AAPL)  (CIK 0000320193)"],
                        "form": "8-K",
                        "file_date": "2026-08-01",
                        "file_type": "8-K",
                    },
                },
            ],
        },
    }


def test_sec_edgar_fts_parse_basic():
    p = SecEdgarProvider()
    result = p._parse_fts(_fts_response(), limit=10)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Apple Inc.  (AAPL) — 10-K"
    assert "sec.gov" in r.url
    assert "aapl-20260627.htm" in r.url
    assert "Period ending: 2026-06-27" in r.snippet
    assert r.published_date == "2026-07-31"
    assert r.provider == "sec_edgar"
    assert r.source == "sec.gov"
    assert r.extra["cik"] == "0000320193"
    assert r.extra["form"] == "10-K"
    assert r.extra["accession_number"] == "0000320193-26-000020"


def test_sec_edgar_fts_parse_fallback_url():
    p = SecEdgarProvider()
    result = p._parse_fts(_fts_response(), limit=10)
    # Second hit has no primary_document -> EDGAR browse URL.
    r = result.results[1]
    assert (
        r.url
        == "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001318605"
    )


def test_sec_edgar_fts_parse_skips_exhibits_and_incomplete():
    p = SecEdgarProvider()
    result = p._parse_fts(_fts_response(), limit=10)
    titles = [r.title for r in result.results]
    assert all("EX-" not in title for title in titles)
    assert all("— 8-K" not in title for title in titles)


def test_sec_edgar_fts_parse_empty():
    p = SecEdgarProvider()
    result = p._parse_fts({"hits": {"hits": []}}, limit=10)
    assert result.results == []


def test_sec_edgar_fts_parse_missing_hits():
    p = SecEdgarProvider()
    result = p._parse_fts({}, limit=10)
    assert result.results == []


def test_sec_edgar_fts_parse_respects_limit():
    p = SecEdgarProvider()
    result = p._parse_fts(_fts_response(), limit=1)
    assert len(result.results) == 1


# ---------------------------------------------------------------------------
# Company submissions parsing
# ---------------------------------------------------------------------------


def _submissions_response() -> dict:
    return {
        "cik": 320193,
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                # "4" (Form 4 insider trading) is intentionally omitted.
                "form": ["10-Q", "8-K", "10-K", "EX-31"],
                "filingDate": [
                    "2026-07-31",
                    "2026-07-30",
                    "2025-11-03",
                    "2025-11-03",
                ],
                "accessionNumber": [
                    "0000320193-26-000020",
                    "0000320193-26-000018",
                    "0000320193-25-000045",
                    "0000320193-25-000046",
                ],
                "primaryDocument": [
                    "aapl-20260627.htm",
                    "aapl-20260730.htm",
                    "aapl-20250925.htm",
                    "ex31-1.htm",
                ],
                "reportDate": [
                    "2026-06-27",
                    "2026-07-30",
                    "2025-09-25",
                    "2025-09-25",
                ],
            },
        },
    }


def test_sec_edgar_filings_parse_basic():
    p = SecEdgarProvider()
    result = p._parse_filings(_submissions_response(), limit=10)

    assert len(result.results) == 3  # EX-31 skipped
    r = result.results[0]
    assert r.title == "Apple Inc. — 10-Q"
    assert "000032019326000020" in r.url  # dashes stripped in the path segment
    assert "aapl-20260627.htm" in r.url
    assert r.published_date == "2026-07-31"
    assert r.extra["report_date"] == "2026-06-27"
    assert r.extra["form"] == "10-Q"


def test_sec_edgar_filings_parse_respects_limit():
    p = SecEdgarProvider()
    result = p._parse_filings(_submissions_response(), limit=1)
    assert len(result.results) == 1
    assert result.results[0].extra["form"] == "10-Q"


def test_sec_edgar_filings_parse_empty_recent():
    p = SecEdgarProvider()
    result = p._parse_filings(
        {"cik": 320193, "name": "Apple Inc.", "filings": {"recent": {}}},
        limit=10,
    )
    assert result.results == []


def test_sec_edgar_filings_parse_unknown_company():
    p = SecEdgarProvider()
    result = p._parse_filings({}, limit=10)
    assert result.results == []


# ---------------------------------------------------------------------------
# Search dispatch / availability
# ---------------------------------------------------------------------------


def test_sec_edgar_is_available_requires_unstable_flag():
    p = SecEdgarProvider()
    # Default settings: unstable providers disabled -> unavailable.
    assert p.is_available() is False


@pytest.mark.asyncio
async def test_sec_edgar_search_company_path(monkeypatch):
    p = SecEdgarProvider()

    async def fake_search_company(query: str, limit: int):
        assert query == "AAPL"
        assert limit == 10
        return p._parse_filings(_submissions_response(), limit=10)

    monkeypatch.setattr(p, "_search_company", fake_search_company)
    result = await p.search("AAPL", _params())
    assert len(result.results) == 3


@pytest.mark.asyncio
async def test_sec_edgar_search_company_path_empty_falls_back_to_fts(monkeypatch):
    p = SecEdgarProvider()
    calls: list[str] = []

    async def empty_company(query: str, limit: int):
        calls.append("company")
        from metasearchmcp.contracts import ProviderResult

        return ProviderResult(results=[])

    async def fake_fts(query: str, limit: int):
        calls.append("fts")
        from metasearchmcp.contracts import ProviderResult

        return ProviderResult(results=[])

    monkeypatch.setattr(p, "_search_company", empty_company)
    monkeypatch.setattr(p, "_search_full_text", fake_fts)
    result = await p.search("AAPL", _params())
    assert calls == ["company", "fts"]
    assert result.results == []


@pytest.mark.asyncio
async def test_sec_edgar_search_fts_path_for_phrase(monkeypatch):
    p = SecEdgarProvider()

    async def fake_fts(query: str, limit: int):
        assert query == "quarterly results"
        return p._parse_filings(_submissions_response(), limit=10)

    monkeypatch.setattr(p, "_search_full_text", fake_fts)
    result = await p.search("quarterly results", _params())
    assert len(result.results) == 3


def _params():
    from metasearchmcp.contracts import SearchParams

    return SearchParams(num_results=10)
