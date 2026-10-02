"""Visual-novel search via the keyless VNDB Kana API.

``VNDB`` (https://vndb.org) — the Visual Novel Database — is a community
catalogue of visual novels.  Its public ``Kana`` API is keyless and speaks
JSON over ``POST``::

    POST https://api.vndb.org/kana/vn
    {"filters": ["search", "=", QUERY], "fields": "...", "results": N,
     "sort": "searchrank"}

The response is a mapping with ``more`` (whether further pages exist) and
``results`` — one object per matching visual novel, carrying its ``id``,
``title``/``alttitle``, ``released`` date, ``rating`` (a 0-100 score),
``votecount``, cover ``image.url``, description, ``developers`` and
``platforms``.  A query that matches nothing answers with an empty
``results`` list.

This complements the anime/manga providers (AniList, Kitsu, MangaDex) with
the *visual novel* medium.  No API key is required.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.vndb.org/kana/vn"
# VNDB has no per-entry HTML path beyond ``/v<id>``; this is the canonical
# human-facing page for a visual novel.
_VN_BASE = "https://vndb.org"
# Fields requested from the API.  Kept to stable, well-documented fields so
# the payload stays small for agents.
_FIELDS = (
    "id, title, alttitle, released, rating, votecount, "
    "image.url, description, developers.name, platforms"
)
# VNDB serves up to 100 results per page; cap well below that.
_MAX_API_RESULTS = 50
# VNDB descriptions use light markup (``[url=...]label[/url]``,
# ``[spoiler]...[/spoiler]``, ``[b]``, ...).  Strip the tags so snippets read
# as plain prose.
_FORMAT_TAG_RE = re.compile(
    r"\[/?(?:url|spoiler|b|i|u|s|code|quote)(?:=[^\]]*)?\]",
    re.IGNORECASE,
)


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field, stripping VNDB markup."""
    if not value:
        return ""
    text = _FORMAT_TAG_RE.sub(" ", str(value))
    return " ".join(text.split())


def _string_list(value: Any) -> list[str]:
    """Return a list of cleaned, non-empty strings from *value*."""
    if not isinstance(value, list):
        return []
    return [cleaned for item in value if (cleaned := _clean(item))]


def _names(value: Any) -> list[str]:
    """Return the cleaned ``name`` of each dict in *value*."""
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if isinstance(item, dict):
            name = _clean(item.get("name"))
            if name:
                names.append(name)
    return names


class VNDBProvider(BaseProvider):
    """Search visual novels on the keyless VNDB Kana API.

    One result is produced per matching visual novel, ranked by VNDB's own
    search relevance.  Each hit carries the title (with the alternative
    title when present), release date, rating and vote count, developers,
    platforms and cover image, so agents get structured metadata rather
    than prose.
    """

    name = "vndb"
    description = (
        "Search the keyless VNDB (Visual Novel Database) for visual novels "
        "by title, returning release date, rating, developers, platforms "
        "and cover image, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "games", "media"]

    def _build_result(self, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw VNDB visual novel."""
        vid = _clean(item.get("id"))
        if not vid:
            return None
        title = _clean(item.get("title")) or _clean(item.get("alttitle"))
        if not title:
            return None

        alttitle = _clean(item.get("alttitle"))
        released = _clean(item.get("released"))
        rating = item.get("rating")
        if not isinstance(rating, (int, float)) or isinstance(rating, bool):
            rating = None
        votecount = item.get("votecount")
        if not isinstance(votecount, int) or isinstance(votecount, bool):
            votecount = None
        developers = _names(item.get("developers"))
        platforms = _string_list(item.get("platforms"))
        description = _clean(item.get("description"))
        image = item.get("image")
        image_url = _clean(image.get("url")) if isinstance(image, dict) else ""

        snippet_parts: list[str] = []
        if alttitle and alttitle != title:
            snippet_parts.append(alttitle)
        meta: list[str] = []
        if released:
            meta.append(released)
        if rating is not None:
            meta.append(f"rating {rating:g}")
        if votecount:
            meta.append(f"{votecount} votes")
        if developers:
            meta.append(", ".join(developers))
        if meta:
            snippet_parts.append(" · ".join(meta))
        if description:
            snippet_parts.append(description)

        return SearchResult(
            title=title,
            url=f"{_VN_BASE}/{vid}",
            snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
            source="vndb.org",
            rank=rank,
            provider=self.name,
            extra={
                "id": vid,
                "alttitle": alttitle or None,
                "released": released or None,
                "rating": rating,
                "votecount": votecount,
                "developers": developers,
                "platforms": platforms,
                "image_url": image_url or None,
            },
        )

    def _parse(self, payload: object, limit: int) -> ProviderResult:
        """Parse a VNDB Kana response into structured results.

        A body that is not the expected ``{"results": [...]}`` mapping (or a
        non-list ``results``) means no results.  At most *limit* hits are
        returned.
        """
        results: list[SearchResult] = []
        if not isinstance(payload, dict):
            return ProviderResult(results=results)
        items = payload.get("results")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        for item in items:
            if len(results) >= limit:
                break
            if not isinstance(item, dict):
                continue
            built = self._build_result(item, len(results) + 1)
            if built is not None:
                results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search VNDB for visual novels matching *query*.

        A blank query performs no request.  Matches are ranked by VNDB's
        own search relevance (``sort=searchrank``).
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        body = {
            "filters": ["search", "=", cleaned],
            "fields": _FIELDS,
            "results": limit,
            "sort": "searchrank",
        }

        async with self._client() as client:
            resp = await client.post(_API_URL, json=body)
            resp.raise_for_status()
            payload = resp.json()

        return self._parse(payload, limit)
