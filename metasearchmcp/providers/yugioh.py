"""Yu-Gi-Oh! card search via the keyless YGOPRODeck database.

``YGOPRODeck`` (https://db.ygoprodeck.com) maintains a community-curated
Yu-Gi-Oh! Trading Card Game database exposed through its keyless
``cardinfo.php`` endpoint::

    GET https://db.ygoprodeck.com/api/v7/cardinfo.php
        ?fname=dark magician&num=10&offset=0

The ``fname`` parameter performs a case-insensitive *fuzzy* match against card
names.  Each card carries ``name``, ``type``/``race``/``attribute``, its stats
(``atk``/``def``/``level``/``linkval``), the rules ``desc``, its ``archetype``,
banlist status, printings (``card_sets``) and market ``card_prices``.  The API
answers an unmatched query with HTTP 400 and ``{"error": ...}``, which is
treated here as "no results" rather than a failure.  No API key is required.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://db.ygoprodeck.com/api/v7/cardinfo.php"
# YGOPRODeck happily returns every match, so cap results regardless of request.
_MAX_RESULTS = 50


def _clean(value: Any) -> str:
    """Return *value* as a stripped string, or ``""`` when it is not text."""
    return value.strip() if isinstance(value, str) else ""


def _int(value: Any) -> int | None:
    """Return *value* as an int, or ``None`` when it is not a real number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


class YuGiOhProvider(BaseProvider):
    """Search Yu-Gi-Oh! cards in the keyless YGOPRODeck database.

    A free-text query is fuzzy-matched against card names, so partial or
    misspelled names (e.g. ``"dark magic"``) still resolve.  Each hit exposes
    the card type, attribute and race, ATK/DEF, level or link rating, rules
    text, archetype, banlist status, first printing and a market price so
    agents get structured trading-card facts rather than prose.
    """

    name = "yugioh"
    description = (
        "Search Yu-Gi-Oh! Trading Card Game cards from the keyless YGOPRODeck "
        "database by fuzzy card name, returning card type, attribute/race, "
        "ATK/DEF, level or link rating, rules text, archetype, banlist status, "
        "first printing and market price, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "media", "games", "cards"]

    def _build_result(self, card: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw YGOPRODeck card object."""
        name = _clean(card.get("name"))
        if not name:
            return None

        url = _clean(card.get("ygoprodeck_url"))
        if not url:
            url = f"https://ygoprodeck.com/card/?search={quote(name)}"

        card_type = _clean(card.get("humanReadableCardType")) or _clean(
            card.get("type"),
        )
        race = _clean(card.get("race"))
        attribute = _clean(card.get("attribute"))
        archetype = _clean(card.get("archetype"))
        description = _clean(card.get("desc"))
        atk = _int(card.get("atk"))
        defense = _int(card.get("def"))
        level = _int(card.get("level"))
        link_rating = _int(card.get("linkval"))

        snippet_parts: list[str] = []
        if card_type:
            snippet_parts.append(card_type)
        if attribute and race:
            snippet_parts.append(f"{attribute}/{race}")
        elif race:
            snippet_parts.append(race)
        # Link monsters carry a link rating and no level; everything else uses
        # the level field (Xyz monsters report their rank there).
        if link_rating:
            snippet_parts.append(f"Link-{link_rating}")
        elif level:
            snippet_parts.append(f"Level {level}")
        if atk is not None:
            snippet_parts.append(f"ATK {atk}")
        if defense is not None:
            snippet_parts.append(f"DEF {defense}")
        if archetype:
            snippet_parts.append(f"Archetype: {archetype}")

        snippet = " | ".join(snippet_parts)
        if description:
            snippet = f"{snippet} | {description}" if snippet else description
        snippet = snippet[:MAX_SNIPPET_LENGTH]

        banlist = card.get("banlist_info")
        banlist_status: str | None = None
        if isinstance(banlist, dict):
            statuses: list[str] = []
            for label, key in (("TCG", "ban_tcg"), ("OCG", "ban_ocg")):
                value = _clean(banlist.get(key))
                if value:
                    statuses.append(f"{label} {value}")
            if statuses:
                banlist_status = "; ".join(statuses)

        first_set: str | None = None
        set_code: str | None = None
        card_sets = card.get("card_sets")
        if isinstance(card_sets, list) and card_sets and isinstance(card_sets[0], dict):
            first_set = _clean(card_sets[0].get("set_name")) or None
            set_code = _clean(card_sets[0].get("set_code")) or None

        price: str | None = None
        card_prices = card.get("card_prices")
        if (
            isinstance(card_prices, list)
            and card_prices
            and isinstance(card_prices[0], dict)
        ):
            price = _clean(card_prices[0].get("tcgplayer_price")) or None

        return SearchResult(
            title=name,
            url=url,
            snippet=snippet,
            source="db.ygoprodeck.com",
            rank=rank,
            provider=self.name,
            extra={
                "id": card.get("id"),
                "type": card_type or None,
                "race": race or None,
                "attribute": attribute or None,
                "archetype": archetype or None,
                "level": level,
                "link_rating": link_rating,
                "atk": atk,
                "def": defense,
                "banlist": banlist_status,
                "first_set": first_set,
                "set_code": set_code,
                "tcgplayer_price": price,
            },
        )

    def _parse(self, payload: object, limit: int) -> list[SearchResult]:
        """Parse a YGOPRODeck response into ranked results, capped at *limit*."""
        results: list[SearchResult] = []
        if not isinstance(payload, dict):
            return results
        data = payload.get("data")
        if not isinstance(data, list):
            return results

        for card in data:
            if len(results) >= limit:
                break
            if not isinstance(card, dict):
                continue
            built = self._build_result(card, len(results) + 1)
            if built is not None:
                results.append(built)

        return results

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search YGOPRODeck for cards whose name fuzzy-matches *query*.

        A blank query performs no request.  An unmatched query (HTTP 400 with
        an error body) yields an empty result set rather than an exception.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_RESULTS)
        api_params = {"fname": cleaned, "num": str(limit), "offset": "0"}

        async with self._client() as client:
            resp = await client.get(_API_URL, params=api_params)
            if resp.status_code == 400:
                return ProviderResult(results=[])
            resp.raise_for_status()
            payload = resp.json()

        return ProviderResult(results=self._parse(payload, limit))
