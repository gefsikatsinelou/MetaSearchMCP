"""Yahoo Finance stock & ETF search via the unofficial JSON endpoint."""

from __future__ import annotations

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

# Unofficial Yahoo Finance JSON endpoint — no API key required.
# Uses the same endpoint as yfinance and many other open-source tools.
_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
_QUOTE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_MAX_API_RESULTS = 20

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://finance.yahoo.com/",
}


class YahooFinanceProvider(BaseProvider):
    """Yahoo Finance stock & ETF search via the unofficial JSON endpoint.

    No API key required. Returns ticker symbols, company names, and basic
    quote data. Note: unofficial endpoint, may occasionally be unreliable.
    """

    name = "yahoo_finance"
    description = "Stock quotes, summaries, and market data via Yahoo Finance."
    tags = ["finance", "stocks"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search for stock tickers and company names via Yahoo Finance."""
        num = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        async with self._client() as client:
            # Step 1: symbol search
            resp = await client.get(
                _SEARCH_URL,
                params={
                    "q": query,
                    "quotesCount": num,
                    "newsCount": 0,
                    "listsCount": 0,
                },
                headers=_HEADERS,
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []

        quotes = data.get("quotes", [])
        for i, item in enumerate(quotes, start=1):
            symbol = item.get("symbol", "")
            name = item.get("longname") or item.get("shortname") or symbol
            exchange = item.get("exchange", "")
            q_type = item.get("quoteType", "")
            sector = item.get("sector", "")

            snippet_parts = []
            if q_type:
                snippet_parts.append(q_type)
            if exchange:
                snippet_parts.append(f"Exchange: {exchange}")
            if sector:
                snippet_parts.append(f"Sector: {sector}")

            results.append(
                SearchResult(
                    title=f"{symbol} — {name}",
                    url=f"https://finance.yahoo.com/quote/{symbol}",
                    snippet=" | ".join(snippet_parts),
                    source="finance.yahoo.com",
                    rank=i,
                    provider=self.name,
                    extra={
                        "symbol": symbol,
                        "exchange": exchange,
                        "quote_type": q_type,
                        "sector": sector,
                    },
                ),
            )

        return ProviderResult(results=results)
