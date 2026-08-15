"""Steam Store game search via the keyless public store search API.

``GET https://store.steampowered.com/api/storesearch/?term=QUERY`` returns
matching games and software from the Steam catalog as JSON. No API key or
authentication is required.

Each hit carries the app name, store page, price (in minor currency units),
Metacritic score, supported platforms, controller support, and a capsule
thumbnail. ``type`` distinguishes ``app`` (games/software) from other catalog
entries such as ``sub`` (packages) or ``bundle``.

Note: the endpoint is best-effort and community-facing; results are limited
to the first page (up to 10 items).
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://store.steampowered.com/api/storesearch"
# The store search endpoint returns at most this many items per request.
_MAX_API_RESULTS = 10

# Platform keys returned by the API, mapped to readable names.
_PLATFORM_LABELS: tuple[tuple[str, str], ...] = (
    ("windows", "Windows"),
    ("mac", "macOS"),
    ("linux", "Linux"),
)


class SteamProvider(BaseProvider):
    """Search games and software on the Steam Store.

    Uses the keyless store search API, which requires no authentication and
    returns structured catalog metadata: app name, store page URL, price,
    Metacritic score, supported platforms, controller support, and thumbnail.
    """

    name = "steam"
    description = (
        "Search video games and software on the Steam Store — price, "
        "Metacritic score, platforms, and controller support via the keyless "
        "Steam store search API."
    )
    tags: ClassVar[list[str]] = ["games", "media"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _format_price(price: object) -> str:
        """Format a price object like ``{"final": 5999, "currency": "USD"}``.

        Prices are expressed in minor currency units (cents). Returns an
        empty string when the item is free or the price is missing.
        """
        if not isinstance(price, dict):
            return ""
        cents = price.get("final")
        currency = str(price.get("currency") or "").strip()
        if cents is None or cents == 0 or not currency:
            return ""
        try:
            return f"{int(cents) / 100:.2f} {currency}"
        except (TypeError, ValueError):
            return ""

    @staticmethod
    def _platforms(item: dict[str, Any]) -> list[str]:
        """Return the list of supported platform names for an item."""
        platforms = item.get("platforms")
        if not isinstance(platforms, dict):
            return []
        return [label for key, label in _PLATFORM_LABELS if platforms.get(key) is True]

    def _parse(self, data: Any) -> ProviderResult:
        """Parse the store search response into structured search results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        for i, item in enumerate(data.get("items") or [], start=1):
            if not isinstance(item, dict):
                continue

            app_id = item.get("id")
            name = self._clean_text(item.get("name"))
            if not app_id or not name:
                continue

            url = f"https://store.steampowered.com/app/{app_id}/"
            metascore = item.get("metascore")
            platforms = self._platforms(item)
            price = self._format_price(item.get("price"))

            snippet_parts: list[str] = []
            if price:
                snippet_parts.append(f"Price: {price}")
            if metascore:
                snippet_parts.append(f"Metascore: {metascore}")
            if platforms:
                snippet_parts.append(f"Platforms: {', '.join(platforms)}")
            if item.get("controller_support"):
                snippet_parts.append(
                    f"Controller: {self._clean_text(item.get('controller_support'))}",
                )

            results.append(
                SearchResult(
                    title=name,
                    url=url,
                    snippet=" | ".join(snippet_parts),
                    source="store.steampowered.com",
                    rank=i,
                    provider=self.name,
                    extra={
                        "app_id": app_id,
                        "type": str(item.get("type") or ""),
                        "thumbnail_url": str(item.get("tiny_image") or ""),
                        "price": price,
                        "metascore": str(metascore) if metascore else "",
                        "platforms": platforms,
                        "controller_support": str(item.get("controller_support") or ""),
                        "streaming_video": bool(item.get("streamingvideo")),
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the Steam Store for games matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={"term": query, "cc": "US", "l": "en"},
            )
            resp.raise_for_status()
            data = resp.json()

        result = self._parse(data)
        # Truncate to the requested limit (the API returns up to 10 items).
        result.results = result.results[:limit]
        return result
