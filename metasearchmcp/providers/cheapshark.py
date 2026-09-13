"""CheapShark game-deal search via the keyless CheapShark APIs.

CheapShark (cheapshark.com) tracks current discounts for PC games across
digital storefronts (Steam, GOG, Epic, Fanatical, ...).  Three public,
keyless JSON endpoints are used:

* ``GET https://www.cheapshark.com/api/1.0/deals`` — games that are on sale
  right now, with the sale price, normal price, savings percentage, store id,
  Metacritic/Steam ratings and release date.
* ``GET https://www.cheapshark.com/api/1.0/games`` — the tracked catalogue,
  used as a fallback when no active discount matches the query so that
  full-price titles still resolve.
* ``GET https://www.cheapshark.com/api/1.0/stores`` — the store-id to
  store-name map, fetched at most once per process and then cached.

Deals are deduplicated by game: a title that is on sale in several stores
shows up once, keeping the best-ranked deal the API reports for it.  This
complements :mod:`metasearchmcp.providers.steam` (store catalogue search) and
:mod:`metasearchmcp.providers.scryfall` (trading cards) by answering what a
game costs right now and where it is cheapest.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_DEALS_URL = "https://www.cheapshark.com/api/1.0/deals"
_GAMES_URL = "https://www.cheapshark.com/api/1.0/games"
_STORES_URL = "https://www.cheapshark.com/api/1.0/stores"
_REDIRECT_URL = "https://www.cheapshark.com/redirect?dealID="
# CheapShark serves up to 60 entries per page; keep pages small for agents.
_MAX_API_RESULTS = 30
# Oversample deals so that per-game deduplication still yields a full page.
_DEALS_PAGE_FACTOR = 3


class CheapSharkProvider(BaseProvider):
    """Search current PC game price drops across digital storefronts.

    Keyless. Queries the CheapShark deals endpoint and falls back to the
    tracked game catalogue when nothing is currently discounted.  Each result
    carries the sale price, the normal price, the discount, the store and the
    Metacritic/Steam rating when available.
    """

    name = "cheapshark"
    description = (
        "Current PC game deals and price drops across digital storefronts "
        "(Steam, GOG, Epic, ...) — sale price, discount, store and ratings, "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["shopping", "deals", "games", "web"]

    # store id -> store name.  CheapShark changes the store list rarely, so it
    # is resolved on first use and reused for the lifetime of the process.
    _store_cache: ClassVar[dict[str, str]] = {}

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if value is None:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _as_float(value: object) -> float | None:
        """Return *value* as a float, or ``None`` when it is not numeric."""
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _as_int(value: object) -> int | None:
        """Return *value* as an int, or ``None`` when it is not numeric."""
        number = CheapSharkProvider._as_float(value)
        return int(number) if number is not None else None

    @staticmethod
    def _iso_date(value: object) -> str | None:
        """Convert a Unix timestamp to a ``YYYY-MM-DD`` UTC date string."""
        timestamp = CheapSharkProvider._as_float(value)
        if not timestamp:
            return None
        try:
            moment = datetime.fromtimestamp(timestamp, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
        return moment.date().isoformat()

    @staticmethod
    def _parse_stores(data: object) -> dict[str, str]:
        """Index a CheapShark stores response by store id."""
        if not isinstance(data, list):
            return {}
        names: dict[str, str] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            store_id = CheapSharkProvider._clean_text(item.get("storeID"))
            store_name = CheapSharkProvider._clean_text(item.get("storeName"))
            if store_id and store_name:
                names[store_id] = store_name
        return names

    def _deal_snippet(
        self,
        item: dict[str, Any],
        store: str,
        sale_price: float | None,
        normal_price: float | None,
        savings: float | None,
    ) -> str:
        """Compose the snippet for a single deal entry."""
        parts: list[str] = []
        if sale_price is not None:
            price = f"On sale: ${sale_price:.2f}"
            if normal_price is not None and normal_price > sale_price:
                price += f" (was ${normal_price:.2f}"
                if savings:
                    price += f", {savings:.0f}% off"
                price += ")"
            parts.append(price)
        if store:
            parts.append(f"at {store}")
        metacritic = self._as_int(item.get("metacriticScore"))
        if metacritic:
            parts.append(f"Metacritic {metacritic}")
        rating_text = self._clean_text(item.get("steamRatingText"))
        if rating_text:
            label = f"Steam: {rating_text}"
            rating_percent = self._as_int(item.get("steamRatingPercent"))
            if rating_percent:
                label += f" ({rating_percent}%)"
            parts.append(label)
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_deal(
        self,
        item: dict[str, Any],
        stores: dict[str, str],
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw deal entry."""
        game_id = self._clean_text(item.get("gameID"))
        title = self._clean_text(item.get("title"))
        deal_id = self._clean_text(item.get("dealID"))
        if not game_id or not title or not deal_id:
            return None

        store_id = self._clean_text(item.get("storeID"))
        store = stores.get(store_id, store_id)
        sale_price = self._as_float(item.get("salePrice"))
        normal_price = self._as_float(item.get("normalPrice"))
        savings = self._as_float(item.get("savings"))
        release_date = self._iso_date(item.get("releaseDate"))
        rating_text = self._clean_text(item.get("steamRatingText"))
        app_id = self._clean_text(item.get("steamAppID"))

        return SearchResult(
            title=title,
            url=f"{_REDIRECT_URL}{deal_id}",
            snippet=self._deal_snippet(item, store, sale_price, normal_price, savings),
            source="cheapshark.com",
            rank=rank,
            provider=self.name,
            published_date=release_date,
            extra={
                "game_id": game_id,
                "deal_id": deal_id,
                "store_id": store_id or None,
                "store": store or None,
                "sale_price": sale_price,
                "normal_price": normal_price,
                "savings_percent": round(savings, 2) if savings is not None else None,
                "deal_rating": self._as_float(item.get("dealRating")),
                "metacritic_score": self._as_int(item.get("metacriticScore")) or None,
                "steam_rating_text": rating_text or None,
                "steam_app_id": app_id or None,
                "is_on_sale": self._clean_text(item.get("isOnSale")) == "1",
                "release_date": release_date,
                "thumb": self._clean_text(item.get("thumb")) or None,
            },
        )

    def _parse_deals(
        self,
        data: object,
        stores: dict[str, str],
        limit: int,
    ) -> ProviderResult:
        """Parse a deals response, keeping the first (best) deal per game."""
        results: list[SearchResult] = []
        if not isinstance(data, list):
            return ProviderResult(results=results)

        seen_games: set[str] = set()
        for item in data:
            if not isinstance(item, dict):
                continue
            game_id = self._clean_text(item.get("gameID"))
            if not game_id or game_id in seen_games:
                continue
            result = self._build_deal(item, stores, len(results) + 1)
            if result is None:
                continue
            seen_games.add(game_id)
            results.append(result)
            if len(results) >= limit:
                break
        return ProviderResult(results=results)

    def _parse_games(self, data: object, limit: int) -> ProviderResult:
        """Parse a catalogue response (fallback when nothing is on sale)."""
        results: list[SearchResult] = []
        if not isinstance(data, list):
            return ProviderResult(results=results)

        for item in data:
            if not isinstance(item, dict):
                continue
            game_id = self._clean_text(item.get("gameID"))
            title = self._clean_text(item.get("external"))
            cheapest = self._as_float(item.get("cheapest"))
            if not game_id or not title:
                continue
            deal_id = self._clean_text(item.get("cheapestDealID"))
            if deal_id:
                url = f"{_REDIRECT_URL}{deal_id}"
            else:
                url = f"https://www.cheapshark.com/redirect?gameID={game_id}"
            snippet = (
                f"Cheapest tracked price: ${cheapest:.2f}"
                if cheapest is not None
                else ""
            )
            app_id = self._clean_text(item.get("steamAppID"))
            internal_name = self._clean_text(item.get("internalName"))
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet[:MAX_SNIPPET_LENGTH],
                    source="cheapshark.com",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "game_id": game_id,
                        "cheapest_price": cheapest,
                        "steam_app_id": app_id or None,
                        "internal_name": internal_name or None,
                        "thumb": self._clean_text(item.get("thumb")) or None,
                    },
                ),
            )
            if len(results) >= limit:
                break
        return ProviderResult(results=results)

    async def _store_names(self, client: httpx.AsyncClient) -> dict[str, str]:
        """Return the store-id -> store-name map, cached across searches."""
        if self._store_cache:
            return self._store_cache
        try:
            resp = await client.get(_STORES_URL)
            resp.raise_for_status()
        except httpx.HTTPError:
            # Store names are cosmetic: a failure must not break the search.
            return {}
        names = self._parse_stores(resp.json())
        if names:
            CheapSharkProvider._store_cache = names
        return names

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search CheapShark for deals matching *query*.

        Currently discounted games come first; when the query matches no
        active discount, the tracked catalogue is searched instead so that
        full-price titles still resolve.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            stores = await self._store_names(client)

            page_size = min(limit * _DEALS_PAGE_FACTOR, _MAX_API_RESULTS * 2)
            deals_resp = await client.get(
                _DEALS_URL,
                params={
                    "title": cleaned,
                    "pageSize": page_size,
                    "pageNumber": 0,
                    "onSale": 1,
                },
            )
            deals_resp.raise_for_status()
            deals = self._parse_deals(deals_resp.json(), stores, limit)
            if deals.results:
                return deals

            games_resp = await client.get(
                _GAMES_URL,
                params={"title": cleaned, "limit": limit},
            )
            games_resp.raise_for_status()
            return self._parse_games(games_resp.json(), limit)
