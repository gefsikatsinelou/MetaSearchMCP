"""Search Dungeons & Dragons reference content with the keyless D&D 5e API.

``dnd5eapi.co`` serves the Open Game Content of the fifth-edition System
Reference Document — spells, monsters, equipment and more — without an API
key.  Each collection exposes a case-insensitive, partial ``name`` filter::

    GET https://www.dnd5eapi.co/api/2014/spells?name=fire

so ``fire`` finds *Fireball*, *Fire Bolt* and *Fire Shield*, and ``dragon``
finds every dragon in the monster manual.  This provider queries the three
highest-value collections (spells, monsters and equipment), merges the hits,
ranking exact-name matches ahead of prefix and substring matches, and links
each hit to its canonical record on ``dnd5eapi.co``.  No API key is required.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_BASE = "https://www.dnd5eapi.co/api/2014"
_SITE_BASE = "https://www.dnd5eapi.co"
_SOURCE = "dnd5eapi.co"
# Collections searched, in priority order; the label renders in the snippet.
_COLLECTIONS: tuple[tuple[str, str], ...] = (
    ("spells", "Spell"),
    ("monsters", "Monster"),
    ("equipment", "Equipment"),
)
# Cap the number of matches surfaced across all collections.
_MAX_API_RESULTS = 25


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field, returning ``""`` for empties."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _is_int(value: object) -> bool:
    """Return True for a genuine integer (excluding ``bool`` and non-numbers)."""
    return isinstance(value, int) and not isinstance(value, bool)


class Dnd5eProvider(BaseProvider):
    """Search D&D 5e spells, monsters and equipment on the keyless 5e API."""

    name = "dnd5e"
    description = (
        "Search Dungeons & Dragons 5e reference content via the keyless D&D "
        "5e API: spells (with their level), monsters and equipment by name, "
        "with each hit linked to its canonical dnd5eapi.co record, no API key "
        "required."
    )
    tags: ClassVar[list[str]] = ["games", "reference", "fiction", "web"]

    @staticmethod
    def _entries(payload: object) -> list[dict[str, Any]]:
        """Return the result entries from a collection response, or ``[]``."""
        if not isinstance(payload, dict):
            return []
        results = payload.get("results")
        if not isinstance(results, list):
            return []
        return [item for item in results if isinstance(item, dict)]

    async def _fetch_collection(
        self,
        client: Any,
        collection: str,
        query: str,
    ) -> list[dict[str, Any]]:
        """Fetch the name matches for one collection.

        A ``404`` (unknown collection) is treated as an empty result set.  Any
        other transport or server error propagates to the caller, which keeps
        the per-collection failures isolated via :func:`asyncio.gather`.
        """
        resp = await client.get(
            f"{_API_BASE}/{collection}",
            params={"name": query},
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return self._entries(resp.json())

    @staticmethod
    def _tier(name: str, query: str) -> int:
        """Rank a name as exact (0), prefix (1) or substring (2) match."""
        lowered = name.lower()
        if lowered == query:
            return 0
        if lowered.startswith(query):
            return 1
        return 2

    @classmethod
    def _build_result(
        cls,
        entry: dict[str, Any],
        label: str,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a 5e API list entry, or ``None``."""
        name = _clean(entry.get("name"))
        if not name:
            return None

        path = _clean(entry.get("url"))
        url = f"{_SITE_BASE}{path}" if path.startswith("/") else _API_BASE

        parts = [label]
        level = entry.get("level")
        if _is_int(level):
            parts.append(f"level {level}")

        extra: dict[str, Any] = {"type": label.lower()}
        index = _clean(entry.get("index"))
        if index:
            extra["index"] = index
        if _is_int(level):
            extra["level"] = level

        return SearchResult(
            title=name,
            url=url,
            snippet=" | ".join(parts)[:MAX_SNIPPET_LENGTH],
            source=_SOURCE,
            rank=rank,
            provider=cls.name,
            extra=extra,
        )

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search 5e spells, monsters and equipment for names matching *query*.

        A blank query performs no request.  The collections are queried
        concurrently; a collection that errors is skipped rather than failing
        the whole search.  Hits are merged and ranked exact-name first, then
        prefix, then substring matches, capped to the requested count.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        async with self._client() as client:
            responses = await asyncio.gather(
                *(
                    self._fetch_collection(client, collection, cleaned)
                    for collection, _label in _COLLECTIONS
                ),
                return_exceptions=True,
            )

        lowered = cleaned.lower()
        # (tier, collection order, position within collection, label, entry)
        merged: list[tuple[int, int, int, str, dict[str, Any]]] = []
        for order, ((_collection, label), entries) in enumerate(
            zip(_COLLECTIONS, responses, strict=True)
        ):
            # Exceptions from a failed collection are skipped, not raised.
            if not isinstance(entries, list):
                continue
            for pos, entry in enumerate(entries):
                name = _clean(entry.get("name"))
                if not name:
                    continue
                merged.append(
                    (self._tier(name, lowered), order, pos, label, entry),
                )

        merged.sort(key=lambda item: item[:3])

        results: list[SearchResult] = []
        for _tier, _order, _pos, label, entry in merged:
            if len(results) >= limit:
                break
            built = self._build_result(entry, label, len(results) + 1)
            if built is not None:
                results.append(built)
        return ProviderResult(results=results)
