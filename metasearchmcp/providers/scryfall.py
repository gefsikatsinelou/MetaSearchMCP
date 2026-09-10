"""Scryfall Magic: The Gathering card search via the public keyless API.

Scryfall indexes every printed Magic: The Gathering card and exposes a
read-only, keyless search API:

``GET https://api.scryfall.com/cards/search?q=QUERY&order=name&limit=N``

A bare query performs a full-text match across card names and rules text
(Scryfall also accepts richer syntax such as ``t:creature c:g``).  Each hit
carries the card name, mana cost, type line, oracle text, set, rarity,
artist, release date, market prices and a link to the official Scryfall
card page.  This complements the existing games provider (Steam) with the
trading-card-game ecosystem, which none of them cover.
"""

from __future__ import annotations

from typing import ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.scryfall.com/cards/search"


def _clean(value: object) -> str:
    """Collapse whitespace and control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


class ScryfallProvider(BaseProvider):
    """Search Magic: The Gathering cards indexed by Scryfall.

    Keyless.  Covers every printed MTG card: name, mana cost, type line,
    rules text, set and rarity, artist, release date, and USD/EUR market
    prices, plus a link to the card's page on scryfall.com.
    """

    name = "scryfall"
    description = (
        "Search Magic: The Gathering cards (names, rules text, sets, "
        "rarities, market prices) via the Scryfall API, no key required."
    )
    tags: ClassVar[list[str]] = ["web", "media", "games", "cards"]

    @staticmethod
    def _first_face(card: dict[str, object], field: str) -> str:
        """Return *field* from the first card face that defines it.

        Double-faced / split cards keep per-face values inside
        ``card_faces`` instead of at the top level.
        """
        faces = card.get("card_faces")
        if not isinstance(faces, list):
            return ""
        for face in faces:
            if isinstance(face, dict):
                value = _clean(face.get(field))
                if value:
                    return value
        return ""

    def _oracle_text(self, card: dict[str, object]) -> str:
        """Return a card's rules text, joining multi-face text when present."""
        text = _clean(card.get("oracle_text"))
        if text:
            return text
        faces = card.get("card_faces")
        if isinstance(faces, list):
            parts = [
                _clean(face.get("oracle_text"))
                for face in faces
                if isinstance(face, dict)
            ]
            return " // ".join(part for part in parts if part)
        return ""

    def _mana_cost(self, card: dict[str, object]) -> str:
        """Return a card's mana cost, falling back to the first face's cost."""
        return _clean(card.get("mana_cost")) or self._first_face(card, "mana_cost")

    @staticmethod
    def _card_url(card: dict[str, object]) -> str:
        """Build a link to the card's page on scryfall.com.

        Prefers the canonical ``scryfall_uri`` (minus its tracking query
        string), falling back to the ``/card/SET/NUMBER`` path and finally
        to a scoped site search so a link is always returned.
        """
        uri = _clean(card.get("scryfall_uri"))
        if uri:
            return uri.split("?", 1)[0]
        set_code = _clean(card.get("set"))
        number = _clean(card.get("collector_number"))
        if set_code and number:
            return f"https://scryfall.com/card/{set_code}/{number}"
        return f"https://scryfall.com/search?q={quote(_clean(card.get('name')))}"

    @staticmethod
    def _price_summary(prices: object) -> str:
        """Summarize USD/EUR market prices into a short readable string."""
        if not isinstance(prices, dict):
            return ""
        parts: list[str] = []
        for key, symbol in (("usd", "$"), ("eur", "€")):
            amount = _clean(prices.get(key))
            if amount:
                parts.append(f"{symbol}{amount}")
        return " / ".join(parts)

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a Scryfall search response into structured results."""
        results: list[SearchResult] = []
        cards = data.get("data") if isinstance(data, dict) else data
        if not isinstance(cards, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for card in cards:
            if len(results) >= max_results:
                break
            if not isinstance(card, dict):
                continue
            name = _clean(card.get("name"))
            if not name:
                continue

            type_line = _clean(card.get("type_line"))
            oracle = self._oracle_text(card)
            set_name = _clean(card.get("set_name"))
            set_code = _clean(card.get("set")).upper()
            rarity = _clean(card.get("rarity"))
            mana_cost = self._mana_cost(card)
            prices = card.get("prices")
            if not isinstance(prices, dict):
                prices = {}

            # Core text: "Type — Rules text", then a metadata tail of
            # rarity, set, and market price.
            core = (
                f"{type_line} — {oracle}"
                if type_line and oracle
                else (type_line or oracle)
            )
            detail_bits: list[str] = []
            if rarity:
                detail_bits.append(rarity.capitalize())
            if set_name:
                detail_bits.append(f"{set_name} ({set_code})" if set_code else set_name)
            price_text = self._price_summary(prices)
            if price_text:
                detail_bits.append(price_text)
            snippet_parts = [core, " | ".join(detail_bits)]

            image_uris = card.get("image_uris")
            image_url = (
                _clean(image_uris.get("normal")) if isinstance(image_uris, dict) else ""
            )
            released = card.get("released_at")

            results.append(
                SearchResult(
                    title=name,
                    url=self._card_url(card),
                    snippet=" | ".join(p for p in snippet_parts if p)[
                        :MAX_SNIPPET_LENGTH
                    ],
                    source="scryfall.com",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=self._iso_date_prefix(
                        released if isinstance(released, str) else None
                    ),
                    extra={
                        "mana_cost": mana_cost,
                        "type_line": type_line,
                        "oracle_text": oracle,
                        "rarity": rarity,
                        "set": set_code,
                        "set_name": set_name,
                        "collector_number": _clean(card.get("collector_number")),
                        "artist": _clean(card.get("artist")),
                        "cmc": card.get("cmc"),
                        "colors": card.get("colors") or [],
                        "prices": prices,
                        "image_url": image_url,
                        "scryfall_uri": _clean(card.get("scryfall_uri")),
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Scryfall for Magic: The Gathering cards matching *query*."""
        limit = min(params.num_results, self._max_results)
        qp = {"q": query, "order": "name", "limit": str(limit)}
        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            if resp.status_code == 404:
                # Scryfall returns 404 when a query matches no cards.
                return ProviderResult(results=[])
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
