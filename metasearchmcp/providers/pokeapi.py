"""Search Pokémon species with the keyless PokéAPI.

``pokeapi.co`` exposes the full National Pokédex — every Pokémon species with
its types, abilities, height, weight and base experience — without an API
key.  The API has no free-text search endpoint, so this provider downloads
the (small, ~1300-entry) name index once, matches the query against it, then
hydrates the best matches with their detailed record::

    GET https://pokeapi.co/api/v2/pokemon?limit=100000
    GET https://pokeapi.co/api/v2/pokemon/{name}

Matches are ranked exact-name first, then prefix matches, then substring
matches.  Each hit carries the National Pokédex number, types, abilities,
height/weight, base experience and a sprite link.  No API key is required.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_BASE = "https://pokeapi.co/api/v2"
_SOURCE = "pokeapi.co"
# A single request with a huge limit returns the whole National Pokédex index.
_INDEX_LIMIT = 100_000
# Cap how many name matches we hydrate with detail requests.
_MAX_API_RESULTS = 20
_SPRITE_BASE = (
    "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon"
)


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field, returning ``""`` for empties."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _dex_id_from_url(url: object) -> int | None:
    """Extract the trailing numeric id from a PokéAPI resource URL."""
    text = _clean(url)
    if not text:
        return None
    parts = [part for part in text.split("/") if part]
    if not parts:
        return None
    try:
        return int(parts[-1])
    except ValueError:
        return None


def _named_values(items: object, key: str) -> list[str]:
    """Flatten ``[{"slot": 1, "type": {"name": "fire"}}]``-style lists.

    PokéAPI nests types and abilities under a named sub-object; this helper
    returns the ordered, cleaned names for the given *key* (``"type"`` or
    ``"ability"``).
    """
    if not isinstance(items, list):
        return []
    values: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        nested = item.get(key)
        if isinstance(nested, dict):
            name = _clean(nested.get("name"))
        else:
            name = _clean(nested)
        if name:
            values.append(name)
    return values


class PokeapiProvider(BaseProvider):
    """Search Pokémon species on the keyless PokéAPI (National Pokédex)."""

    name = "pokeapi"
    description = (
        "Search Pokémon species via the keyless PokéAPI: National Pokédex "
        "number, types, abilities, height, weight, base experience and a "
        "sprite link, no API key required."
    )
    tags: ClassVar[list[str]] = ["media", "games", "fiction", "reference"]

    @staticmethod
    def _entries(payload: object) -> list[dict[str, Any]]:
        """Return the index entries from a PokéAPI list response, or ``[]``."""
        if not isinstance(payload, dict):
            return []
        results = payload.get("results")
        if not isinstance(results, list):
            return []
        return [item for item in results if isinstance(item, dict)]

    @staticmethod
    def _matches(
        entries: list[dict[str, Any]],
        query: str,
    ) -> list[tuple[int | None, str]]:
        """Return ``(dex_id, name)`` pairs matching *query*, best match first.

        Ranking is exact name, then prefix, then substring; ties preserve the
        index order (i.e. Pokédex order).
        """
        matched: list[tuple[int, int, int | None, str]] = []
        for index, entry in enumerate(entries):
            name = _clean(entry.get("name"))
            if not name or query not in name:
                continue
            if name == query:
                tier = 0
            elif name.startswith(query):
                tier = 1
            else:
                tier = 2
            matched.append((tier, index, _dex_id_from_url(entry.get("url")), name))
        matched.sort()
        return [(dex_id, name) for _tier, _index, dex_id, name in matched]

    async def _fetch_detail(
        self,
        client: Any,
        name: str,
    ) -> dict[str, Any] | None:
        """Fetch one Pokémon's detail record, or ``None`` when it is missing."""
        resp = await client.get(f"{_API_BASE}/pokemon/{name}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else None

    @classmethod
    def _build_result(
        cls,
        detail: dict[str, Any],
        dex_id: int | None,
        name: str,
        rank: int,
    ) -> SearchResult:
        """Build one :class:`SearchResult` from a Pokémon detail record."""
        resolved_id = detail.get("id")
        if not isinstance(resolved_id, int) or isinstance(resolved_id, bool):
            resolved_id = dex_id
        title = (_clean(detail.get("name")) or name).capitalize()
        url = (
            f"{_API_BASE}/pokemon/{resolved_id}"
            if resolved_id is not None
            else f"{_API_BASE}/pokemon/{name}"
        )

        parts: list[str] = []
        if resolved_id is not None:
            parts.append(f"#{resolved_id}")

        types = _named_values(detail.get("types"), "type")
        if types:
            parts.append("type: " + ", ".join(types))

        abilities = _named_values(detail.get("abilities"), "ability")
        if abilities:
            parts.append("abilities: " + ", ".join(abilities))

        height = detail.get("height")
        if isinstance(height, int) and not isinstance(height, bool) and height:
            parts.append(f"{height / 10:g} m")

        weight = detail.get("weight")
        if isinstance(weight, int) and not isinstance(weight, bool) and weight:
            parts.append(f"{weight / 10:g} kg")

        base_experience = detail.get("base_experience")
        if isinstance(base_experience, int) and not isinstance(base_experience, bool):
            parts.append(f"base exp. {base_experience}")

        sprites = detail.get("sprites")
        sprite = ""
        if isinstance(sprites, dict):
            sprite = _clean(sprites.get("front_default"))
        if not sprite and resolved_id is not None:
            sprite = f"{_SPRITE_BASE}/{resolved_id}.png"

        extra: dict[str, Any] = {"dex_id": resolved_id, "types": types}
        if abilities:
            extra["abilities"] = abilities
        if sprite:
            extra["sprite"] = sprite

        return SearchResult(
            title=title,
            url=url,
            snippet=" | ".join(parts)[:MAX_SNIPPET_LENGTH],
            source=_SOURCE,
            rank=rank,
            provider=cls.name,
            extra=extra,
        )

    @classmethod
    def _fallback_result(
        cls,
        dex_id: int | None,
        name: str,
        rank: int,
    ) -> SearchResult:
        """Build a minimal result when the detail request cannot be served."""
        title = name.capitalize()
        url = (
            f"{_API_BASE}/pokemon/{dex_id}"
            if dex_id is not None
            else f"{_API_BASE}/pokemon/{name}"
        )
        snippet = f"#{dex_id}" if dex_id is not None else "National Pokédex record"
        extra: dict[str, Any] = {"dex_id": dex_id}
        if dex_id is not None:
            extra["sprite"] = f"{_SPRITE_BASE}/{dex_id}.png"
        return SearchResult(
            title=title,
            url=url,
            snippet=snippet,
            source=_SOURCE,
            rank=rank,
            provider=cls.name,
            extra=extra,
        )

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the National Pokédex for Pokémon whose name matches *query*.

        A blank query performs no request.  The name index is fetched once,
        matched locally, and the best matches are hydrated concurrently;
        individual detail failures degrade gracefully to a minimal result.
        """
        cleaned = query.strip().lower()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        async with self._client() as client:
            resp = await client.get(
                f"{_API_BASE}/pokemon",
                params={"limit": _INDEX_LIMIT},
            )
            resp.raise_for_status()
            matches = self._matches(self._entries(resp.json()), cleaned)[:limit]
            if not matches:
                return ProviderResult(results=[])
            details = await asyncio.gather(
                *(self._fetch_detail(client, name) for _dex_id, name in matches),
                return_exceptions=True,
            )

        results: list[SearchResult] = []
        for rank, ((dex_id, name), detail) in enumerate(
            zip(matches, details, strict=True),
            start=1,
        ):
            if isinstance(detail, dict):
                results.append(self._build_result(detail, dex_id, name, rank))
            else:
                results.append(self._fallback_result(dex_id, name, rank))
        return ProviderResult(results=results)
