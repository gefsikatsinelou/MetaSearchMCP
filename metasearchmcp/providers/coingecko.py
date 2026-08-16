"""CoinGecko cryptocurrency search via the keyless public API.

``GET https://api.coingecko.com/api/v3/search?query=QUERY`` returns matching
cryptocurrencies from CoinGecko's coin database as JSON. No API key or
authentication is required (the public endpoint is rate-limited but free).

Each hit carries the coin id, name, ticker symbol, market-cap rank, and
thumbnail/large image URLs. The endpoint is best-effort and community-facing;
results are limited to the first page (up to 10 coins by default).

Note: CoinGecko's public API is rate-limited; heavy automated use should
respect the documented limits or use the paid API tier.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://api.coingecko.com/api/v3/search"
# The public search endpoint returns at most this many coins per request.
_MAX_API_RESULTS = 10


class CoinGeckoProvider(BaseProvider):
    """Search cryptocurrencies on CoinGecko by name or ticker symbol.

    Uses the keyless public search API, which requires no authentication and
    returns structured coin metadata: name, symbol, market-cap rank, and
    thumbnail/large image URLs.
    """

    name = "coingecko"
    description = (
        "Search cryptocurrencies by name or ticker — market-cap rank and "
        "logo via the keyless CoinGecko public API."
    )
    tags: ClassVar[list[str]] = ["finance", "crypto"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    def _parse(self, data: Any) -> ProviderResult:
        """Parse the search response into structured search results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        coins = data.get("coins")
        if not isinstance(coins, list):
            return ProviderResult(results=results)

        for i, coin in enumerate(coins, start=1):
            if not isinstance(coin, dict):
                continue

            coin_id = self._clean_text(coin.get("id"))
            name = self._clean_text(coin.get("name"))
            if not coin_id or not name:
                continue

            symbol = self._clean_text(coin.get("symbol")).upper()
            market_cap_rank = coin.get("market_cap_rank")

            snippet_parts: list[str] = []
            if symbol:
                snippet_parts.append(f"Symbol: {symbol}")
            if market_cap_rank:
                snippet_parts.append(f"Market cap rank: #{market_cap_rank}")

            results.append(
                SearchResult(
                    title=f"{name} ({symbol})" if symbol else name,
                    url=f"https://www.coingecko.com/en/coins/{coin_id}",
                    snippet=" | ".join(snippet_parts),
                    source="coingecko.com",
                    rank=i,
                    provider=self.name,
                    extra={
                        "coin_id": coin_id,
                        "symbol": symbol,
                        "market_cap_rank": market_cap_rank,
                        "thumbnail_url": str(coin.get("thumb") or ""),
                        "large_image_url": str(coin.get("large") or ""),
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search CoinGecko for cryptocurrencies matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(_API_URL, params={"query": query})
            resp.raise_for_status()
            data = resp.json()

        result = self._parse(data)
        # Truncate to the requested limit (the API returns up to 10 coins).
        result.results = result.results[:limit]
        return result
