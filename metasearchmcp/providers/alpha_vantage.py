"""Alpha Vantage stock search via the official SYMBOL_SEARCH endpoint."""

from __future__ import annotations

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantageProvider(BaseProvider):
    """Alpha Vantage stock search via the official SYMBOL_SEARCH endpoint.

    Free tier: 25 requests/day, 5 requests/minute.
    Get a free key at https://www.alphavantage.co/support/#api-key

    Set ALPHA_VANTAGE_API_KEY in your environment.
    """

    name = "alpha_vantage"
    description = (
        "Real-time and historical stock quotes, forex, "
        "and crypto data via Alpha Vantage API."
    )
    tags = ["finance", "stocks"]

    def __init__(self) -> None:
        super().__init__()
        self._api_key = get_settings().alpha_vantage_api_key

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        async with self._client() as client:
            resp = await client.get(
                _BASE_URL,
                params={
                    "function": "SYMBOL_SEARCH",
                    "keywords": query,
                    "apikey": self._api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []

        for i, match in enumerate(data.get("bestMatches", []), start=1):
            symbol = match.get("1. symbol", "")
            name = match.get("2. name", "")
            q_type = match.get("3. type", "")
            region = match.get("4. region", "")
            currency = match.get("8. currency", "")
            match_score = match.get("9. matchScore", "")

            snippet_parts = []
            if q_type:
                snippet_parts.append(q_type)
            if region:
                snippet_parts.append(f"Region: {region}")
            if currency:
                snippet_parts.append(f"Currency: {currency}")

            results.append(
                SearchResult(
                    title=f"{symbol} — {name}",
                    url=f"https://finance.yahoo.com/quote/{symbol}",
                    snippet=" | ".join(snippet_parts),
                    source="alphavantage.co",
                    rank=i,
                    provider=self.name,
                    extra={
                        "symbol": symbol,
                        "type": q_type,
                        "region": region,
                        "currency": currency,
                        "match_score": match_score,
                    },
                ),
            )

        return ProviderResult(results=results)
