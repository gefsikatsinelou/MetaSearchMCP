from __future__ import annotations

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_BASE_URL = "https://finnhub.io/api/v1"


class FinnhubProvider(BaseProvider):
    """Finnhub stock search via the official API.

    Free tier: 60 API calls/minute.
    Get a free key at https://finnhub.io/register

    Set FINNHUB_API_KEY in your environment.
    """

    name = "finnhub"
    description = (
        "Real-time stock quotes, earnings, and company profiles via Finnhub API."
    )
    tags = ["finance", "stocks"]

    def __init__(self) -> None:
        super().__init__()
        self._api_key = get_settings().finnhub_api_key

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        async with self._client() as client:
            resp = await client.get(
                f"{_BASE_URL}/search",
                params={"q": query, "token": self._api_key},
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, query)

    def _parse(self, data: dict, query: str = "") -> ProviderResult:
        results: list[SearchResult] = []

        count = data.get("count", 0)
        for i, item in enumerate(data.get("result", []), start=1):
            symbol = item.get("symbol", "")
            description = item.get("description", "")
            q_type = item.get("type", "")
            display_symbol = item.get("displaySymbol", symbol)

            snippet_parts = []
            if q_type:
                snippet_parts.append(q_type)
            if display_symbol and display_symbol != symbol:
                snippet_parts.append(f"Display: {display_symbol}")

            results.append(
                SearchResult(
                    title=f"{symbol} — {description}",
                    url=f"https://finance.yahoo.com/quote/{symbol}",
                    snippet=" | ".join(snippet_parts),
                    source="finnhub.io",
                    rank=i,
                    provider=self.name,
                    extra={
                        "symbol": symbol,
                        "type": q_type,
                        "display_symbol": display_symbol,
                        "total_count": count,
                    },
                ),
            )

        return ProviderResult(results=results)
