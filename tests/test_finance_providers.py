"""Unit tests for the three finance providers: yahoo_finance, alpha_vantage, finnhub."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Yahoo Finance
# ---------------------------------------------------------------------------


def _yahoo_finance_response() -> dict:
    return {
        "quotes": [
            {
                "symbol": "AAPL",
                "longname": "Apple Inc.",
                "shortname": "Apple Inc.",
                "exchange": "NMS",
                "quoteType": "EQUITY",
                "sector": "Technology",
            },
            {
                "symbol": "AAPL.BA",
                "longname": None,
                "shortname": "Apple Inc.",
                "exchange": "BUE",
                "quoteType": "EQUITY",
                "sector": "",
            },
        ],
        "news": [],
    }


def test_yahoo_finance_parse_basic():
    from metasearchmcp.providers.yahoo_finance import YahooFinanceProvider

    p = YahooFinanceProvider()
    result = p._parse(_yahoo_finance_response())

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "AAPL — Apple Inc."
    assert r.url == "https://finance.yahoo.com/quote/AAPL"
    assert r.provider == "yahoo_finance"
    assert r.source == "finance.yahoo.com"
    assert r.extra["symbol"] == "AAPL"
    assert r.extra["quote_type"] == "EQUITY"


def test_yahoo_finance_parse_snippet_content():
    from metasearchmcp.providers.yahoo_finance import YahooFinanceProvider

    p = YahooFinanceProvider()
    result = p._parse(_yahoo_finance_response())
    r = result.results[0]
    assert "EQUITY" in r.snippet
    assert "NMS" in r.snippet
    assert "Technology" in r.snippet


def test_yahoo_finance_parse_fallback_shortname():
    from metasearchmcp.providers.yahoo_finance import YahooFinanceProvider

    p = YahooFinanceProvider()
    result = p._parse(_yahoo_finance_response())
    # second item has no longname; should fall back to shortname
    r = result.results[1]
    assert "Apple" in r.title


def test_yahoo_finance_parse_empty():
    from metasearchmcp.providers.yahoo_finance import YahooFinanceProvider

    p = YahooFinanceProvider()
    result = p._parse({"quotes": [], "news": []})
    assert result.results == []


def test_yahoo_finance_parse_ranks():
    from metasearchmcp.providers.yahoo_finance import YahooFinanceProvider

    p = YahooFinanceProvider()
    result = p._parse(_yahoo_finance_response())
    assert result.results[0].rank == 1
    assert result.results[1].rank == 2


# ---------------------------------------------------------------------------
# Alpha Vantage
# ---------------------------------------------------------------------------


def _alpha_vantage_response() -> dict:
    return {
        "bestMatches": [
            {
                "1. symbol": "MSFT",
                "2. name": "Microsoft Corporation",
                "3. type": "Equity",
                "4. region": "United States",
                "5. marketOpen": "09:30",
                "6. marketClose": "16:00",
                "7. timezone": "UTC-04",
                "8. currency": "USD",
                "9. matchScore": "0.8889",
            },
            {
                "1. symbol": "MSFT.LON",
                "2. name": "Microsoft Corporation",
                "3. type": "Equity",
                "4. region": "United Kingdom",
                "5. marketOpen": "08:00",
                "6. marketClose": "16:30",
                "7. timezone": "UTC+01",
                "8. currency": "GBX",
                "9. matchScore": "0.6667",
            },
        ],
    }


def test_alpha_vantage_parse_basic():
    from metasearchmcp.providers.alpha_vantage import AlphaVantageProvider

    p = AlphaVantageProvider()
    result = p._parse(_alpha_vantage_response())

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "MSFT — Microsoft Corporation"
    assert r.url == "https://finance.yahoo.com/quote/MSFT"
    assert r.provider == "alpha_vantage"
    assert r.source == "alphavantage.co"
    assert r.extra["symbol"] == "MSFT"
    assert r.extra["region"] == "United States"
    assert r.extra["currency"] == "USD"
    assert r.extra["match_score"] == "0.8889"


def test_alpha_vantage_parse_snippet():
    from metasearchmcp.providers.alpha_vantage import AlphaVantageProvider

    p = AlphaVantageProvider()
    result = p._parse(_alpha_vantage_response())
    r = result.results[0]
    assert "Equity" in r.snippet
    assert "United States" in r.snippet
    assert "USD" in r.snippet


def test_alpha_vantage_parse_empty():
    from metasearchmcp.providers.alpha_vantage import AlphaVantageProvider

    p = AlphaVantageProvider()
    result = p._parse({"bestMatches": []})
    assert result.results == []


def test_alpha_vantage_parse_rank():
    from metasearchmcp.providers.alpha_vantage import AlphaVantageProvider

    p = AlphaVantageProvider()
    result = p._parse(_alpha_vantage_response())
    assert result.results[0].rank == 1
    assert result.results[1].rank == 2


# ---------------------------------------------------------------------------
# Finnhub
# ---------------------------------------------------------------------------


def _finnhub_response() -> dict:
    return {
        "count": 3,
        "result": [
            {
                "description": "TESLA INC",
                "displaySymbol": "TSLA",
                "symbol": "TSLA",
                "type": "Common Stock",
            },
            {
                "description": "TESLA INC",
                "displaySymbol": "TSLA.SW",
                "symbol": "TSLA.SW",
                "type": "Common Stock",
            },
            {
                "description": "TSLA 3X LONG",
                "displaySymbol": "3TSL",
                "symbol": "3TSL",
                "type": "ETP",
            },
        ],
    }


def test_finnhub_parse_basic():
    from metasearchmcp.providers.finnhub import FinnhubProvider

    p = FinnhubProvider()
    result = p._parse(_finnhub_response())

    assert len(result.results) == 3
    r = result.results[0]
    assert r.title == "TSLA — TESLA INC"
    assert r.url == "https://finance.yahoo.com/quote/TSLA"
    assert r.provider == "finnhub"
    assert r.source == "finnhub.io"
    assert r.extra["symbol"] == "TSLA"
    assert r.extra["type"] == "Common Stock"
    assert r.extra["total_count"] == 3


def test_finnhub_parse_type_in_snippet():
    from metasearchmcp.providers.finnhub import FinnhubProvider

    p = FinnhubProvider()
    result = p._parse(_finnhub_response())
    assert "Common Stock" in result.results[0].snippet


def test_finnhub_parse_display_symbol_differs():
    from metasearchmcp.providers.finnhub import FinnhubProvider

    p = FinnhubProvider()
    result = p._parse(_finnhub_response())
    # TSLA.SW has displaySymbol same as symbol, so no extra "Display:" in snippet
    # 3TSL has displaySymbol "3TSL" same as symbol as well
    r = result.results[0]
    # displaySymbol == symbol, should not add redundant info
    assert "Display: TSLA" not in r.snippet


def test_finnhub_parse_empty():
    from metasearchmcp.providers.finnhub import FinnhubProvider

    p = FinnhubProvider()
    result = p._parse({"count": 0, "result": []})
    assert result.results == []


def test_finnhub_parse_ranks():
    from metasearchmcp.providers.finnhub import FinnhubProvider

    p = FinnhubProvider()
    result = p._parse(_finnhub_response())
    for i, r in enumerate(result.results, start=1):
        assert r.rank == i
