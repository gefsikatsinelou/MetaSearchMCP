"""Poetry search via the keyless PoetryDB API.

``PoetryDB`` (https://poetrydb.org) is a small, keyless JSON API serving a
corpus of public-domain poetry — Shakespeare's sonnets, Poe, Whitman,
Dickinson, Blake, Shelley and many others — together with the full text of
every poem.  It exposes substring search over three fields::

    GET https://poetrydb.org/title/QUERY   # poems whose title contains QUERY
    GET https://poetrydb.org/author/QUERY  # poems by a matching author
    GET https://poetrydb.org/lines/QUERY   # poems whose text contains QUERY

Each match is an object with the poem ``title``, its ``author``, the
``lines`` (a list of strings) and the ``linecount`` as a string.  A query
that matches nothing answers ``{"status": 404, "reason": "Not found"}``
with HTTP status 200, so a non-list body is treated as "no results".

This complements the prose providers (Project Gutenberg, Open Library,
Google Books) with a *poetry* corpus that can be searched by content as
well as by title and author.  No API key is required.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

import httpx

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_BASE = "https://poetrydb.org"
# Fields searched, in priority order: title hits first, then author, then a
# full-text scan of the poem lines.  PoetryDB can only AND fields, not OR
# them, so each field is queried in turn and the matches are merged.
_SEARCH_FIELDS = ("title", "author", "lines")
# PoetryDB has no page-size parameter; results are fetched whole and trimmed.
_MAX_API_RESULTS = 50
# Poem lines quoted in the snippet.
_SNIPPET_LINE_LIMIT = 2
# Poem lines carried in ``extra`` (long poems are truncated to keep payloads
# small for agents; ``truncated`` flags when that happened).
_EXTRA_LINE_LIMIT = 40


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


class PoetryDbProvider(BaseProvider):
    """Search public-domain poetry — by title, author or content — on PoetryDB.

    Keyless.  The query is matched against the poem titles first, then the
    authors, then the full text of the poem lines; the hits are merged and
    deduplicated by title and author, so one query can surface a poem by any
    of the three fields.
    """

    name = "poetrydb"
    description = (
        "Search a corpus of public-domain poetry on the keyless PoetryDB API "
        "by title, author or full text, returning the poem's title, author, "
        "line count and lines, no API key required."
    )
    tags: ClassVar[list[str]] = ["books", "media", "reference"]

    @staticmethod
    def _poem_lines(item: dict[str, Any]) -> list[str]:
        """Return a poem's non-empty lines as trimmed strings."""
        raw_lines = item.get("lines")
        if not isinstance(raw_lines, list):
            return []
        lines: list[str] = []
        for line in raw_lines:
            text = _clean(line)
            if text:
                lines.append(text)
        return lines

    @staticmethod
    def _linecount(item: dict[str, Any], lines: list[str]) -> int | None:
        """Return the poem's line count.

        PoetryDB reports ``linecount`` as a string; when it is missing or
        malformed the parsed lines supply the count instead.  ``None`` means
        the count could not be determined.
        """
        raw = item.get("linecount")
        if isinstance(raw, str) and raw.strip().isdigit():
            return int(raw.strip())
        if isinstance(raw, int) and not isinstance(raw, bool):
            return raw
        return len(lines) or None

    def _build_result(self, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw PoetryDB poem record."""
        title = _clean(item.get("title"))
        if not title:
            return None
        author = _clean(item.get("author"))
        lines = self._poem_lines(item)
        linecount = self._linecount(item, lines)

        snippet_parts: list[str] = []
        if author:
            snippet_parts.append(author)
        if linecount is not None:
            snippet_parts.append(f"{linecount} lines")
        snippet_parts.extend(lines[:_SNIPPET_LINE_LIMIT])

        return SearchResult(
            title=title,
            # PoetryDB has no human-facing poem pages; its per-title endpoint
            # serves the poem's JSON record and is the canonical URL.
            url=f"{_API_BASE}/title/{quote(title, safe='')}",
            snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
            source="poetrydb.org",
            rank=rank,
            provider=self.name,
            extra={
                "author": author or None,
                "linecount": linecount,
                "lines": lines[:_EXTRA_LINE_LIMIT],
                "truncated": len(lines) > _EXTRA_LINE_LIMIT,
            },
        )

    @staticmethod
    def _parse_poems(payload: object) -> list[dict[str, Any]]:
        """Return the poem records of a PoetryDB response, or an empty list.

        A no-match response is the mapping ``{"status": 404, ...}`` (served
        with HTTP 200), so anything that is not a list means "no results".
        """
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    async def _search_field(
        self,
        client: httpx.AsyncClient,
        field: str,
        query: str,
    ) -> list[dict[str, Any]]:
        """Query one PoetryDB field, returning its (possibly empty) poems."""
        url = f"{_API_BASE}/{field}/{quote(query, safe='')}"
        resp = await client.get(url)
        resp.raise_for_status()
        return self._parse_poems(resp.json())

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search PoetryDB for poems matching *query*.

        A blank query performs no request.  The query is matched against the
        poem titles, then the authors, then the full text of the lines; the
        first matches fill the result set, deduplicated by title and author.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        results: list[SearchResult] = []
        seen: set[tuple[str, str]] = set()

        async with self._client() as client:
            for field in _SEARCH_FIELDS:
                if len(results) >= limit:
                    break
                for item in await self._search_field(client, field, cleaned):
                    if len(results) >= limit:
                        break
                    key = (_clean(item.get("title")), _clean(item.get("author")))
                    if not key[0] or key in seen:
                        continue
                    seen.add(key)
                    built = self._build_result(item, len(results) + 1)
                    if built is not None:
                        results.append(built)

        return ProviderResult(results=results)
