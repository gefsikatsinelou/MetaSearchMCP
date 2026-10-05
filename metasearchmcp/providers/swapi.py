"""Search the Star Wars universe with the Star Wars API (SWAPI).

``swapi.dev`` is a free, keyless REST API exposing the Star Wars canon —
people, films, planets, species, starships and vehicles.  Every collection
supports free-text search over its records::

    GET https://swapi.dev/api/people/?search=QUERY
    GET https://swapi.dev/api/films/?search=QUERY

This provider queries all six collections concurrently and then interleaves
their hits round-robin, so a single query surfaces a balanced mix of
characters, films, places, species and craft instead of one collection
dominating the result page.  Each hit carries the record's canonical
``swapi.dev`` URL, a compact fact snippet and the collection it came from.
No API key is required.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import httpx

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_BASE = "https://swapi.dev/api"
_SOURCE = "swapi.dev"
# The six entity collections SWAPI exposes, all searchable by free text.
_RESOURCES: tuple[str, ...] = (
    "people",
    "films",
    "planets",
    "species",
    "starships",
    "vehicles",
)
# SWAPI paginates 10 records per page and cannot be told to return more.
_PAGE_SIZE = 10
# Hard ceiling on one query's hits across all six collections.
_MAX_HITS = _PAGE_SIZE * len(_RESOURCES)


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field, returning ``""`` for empties."""
    if value is None:
        return ""
    return " ".join(str(value).split())


# Placeholder values SWAPI uses where a fact is not known.
_UNKNOWN = {"unknown", "n/a", "none", "indeterminate"}


def _fact(value: object) -> str:
    """Return a cleaned fact, or ``""`` when SWAPI reports it as unknown."""
    text = _clean(value)
    return "" if text.lower() in _UNKNOWN else text


class SwapiProvider(BaseProvider):
    """Search Star Wars characters, films, planets, species and craft on SWAPI."""

    name = "swapi"
    description = (
        "Search the Star Wars universe via the keyless Star Wars API (SWAPI): "
        "characters, films, planets, species, starships and vehicles, with each "
        "record's canonical swapi.dev link and a compact fact snippet, "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["media", "entertainment", "fiction", "reference"]

    @staticmethod
    def _items(payload: object) -> list[dict[str, Any]]:
        """Return the record dicts from a SWAPI page, ignoring malformed input."""
        if not isinstance(payload, dict):
            return []
        results = payload.get("results")
        if not isinstance(results, list):
            return []
        return [item for item in results if isinstance(item, dict)]

    @staticmethod
    def _snippet(resource: str, item: dict[str, Any]) -> str:
        """Build a short ``field | field`` fact snippet for one SWAPI record."""
        parts: list[str] = []
        if resource == "films":
            episode = item.get("episode_id")
            if isinstance(episode, int) and not isinstance(episode, bool):
                parts.append(f"Episode {episode}")
            director = _fact(item.get("director"))
            if director:
                parts.append(f"dir. {director}")
            release = _fact(item.get("release_date"))
            if release:
                parts.append(release)
        elif resource == "people":
            gender = _fact(item.get("gender"))
            if gender:
                parts.append(gender)
            height = _fact(item.get("height"))
            if height:
                parts.append(f"{height} cm")
            mass = _fact(item.get("mass"))
            if mass:
                parts.append(f"{mass} kg")
            birth = _fact(item.get("birth_year"))
            if birth:
                parts.append(f"born {birth}")
        elif resource == "planets":
            for label in ("climate", "terrain", "gravity"):
                value = _fact(item.get(label))
                if value:
                    parts.append(value)
            population = _fact(item.get("population"))
            if population:
                parts.append(f"pop. {population}")
        elif resource == "species":
            for label in ("classification", "designation", "language"):
                value = _fact(item.get(label))
                if value:
                    parts.append(value)
        else:  # starships / vehicles
            for label in ("model", "manufacturer", "starship_class", "vehicle_class"):
                value = _fact(item.get(label))
                if value:
                    parts.append(value)
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    @classmethod
    def _build_result(
        cls,
        resource: str,
        item: dict[str, Any],
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a SWAPI record, or ``None``."""
        title = _clean(item.get("title" if resource == "films" else "name"))
        url = _clean(item.get("url"))
        if not title or not url:
            return None
        if resource == "films":
            published = cls._iso_date_prefix(_clean(item.get("release_date")))
        else:
            published = cls._iso_date_prefix(_clean(item.get("created")))
        return SearchResult(
            title=title,
            url=url,
            snippet=cls._snippet(resource, item),
            source=_SOURCE,
            rank=rank,
            provider=cls.name,
            published_date=published,
            extra={"resource": resource},
        )

    @staticmethod
    def _interleave(
        groups: list[tuple[str, list[dict[str, Any]]]],
    ) -> list[tuple[str, dict[str, Any]]]:
        """Round-robin records from each collection so no single type dominates."""
        ordered: list[tuple[str, dict[str, Any]]] = []
        depth = 0
        while True:
            appended = False
            for resource, items in groups:
                if depth < len(items):
                    ordered.append((resource, items[depth]))
                    appended = True
            if not appended:
                return ordered
            depth += 1

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        resource: str,
        query: str,
    ) -> object:
        """Fetch one SWAPI collection page matching *query*."""
        resp = await client.get(f"{_API_BASE}/{resource}/", params={"search": query})
        resp.raise_for_status()
        return resp.json()

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search every SWAPI collection matching *query*.

        A blank query performs no request.  Hits from the six collections are
        interleaved and truncated to the requested result count.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_HITS)

        async with self._client() as client:
            pages = await asyncio.gather(
                *(self._fetch(client, resource, cleaned) for resource in _RESOURCES),
                return_exceptions=True,
            )

        groups: list[tuple[str, list[dict[str, Any]]]] = []
        errors: list[BaseException] = []
        for resource, page in zip(_RESOURCES, pages, strict=False):
            if isinstance(page, BaseException):
                errors.append(page)
                continue
            items = self._items(page)
            if items:
                groups.append((resource, items))

        # Surface a failure only when every collection errored, so partial
        # outages still yield results from the collections that answered.
        if not groups and errors:
            raise errors[0]

        results: list[SearchResult] = []
        for resource, item in self._interleave(groups):
            if len(results) >= limit:
                break
            built = self._build_result(resource, item, len(results) + 1)
            if built is not None:
                results.append(built)
        return ProviderResult(results=results)
