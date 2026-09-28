"""Podcast *episode* search via the keyless fyyd API.

``fyyd`` (https://fyyd.de) is an independent, community-curated podcast
directory that indexes well over a hundred thousand shows together with their
episodes.  Its public JSON API requires no key::

    GET https://api.fyyd.de/0.2/search/episode?term=QUERY&count=N

That endpoint matches *episodes* — the level the existing ``itunes`` provider,
which searches podcast *shows*, does not cover.  Each hit carries the episode
title and description, the original episode page, the audio enclosure URL and
its MIME type, the publication date, the duration, the season/episode numbers
and artwork, plus a link to the episode's fyyd page.

Queries that match no episode fall back to the show-level endpoint
(``/0.2/search/podcast``) so that searching for a programme by name still
returns the show itself, with its author, language, feed URL, episode count,
artwork and fyyd page.

Both endpoints answer with ``{"status": 1, "msg": "ok", "data": [...]}``; a
status other than ``1`` or a missing ``data`` list is treated as "no results".
No API key is required.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_BASE = "https://api.fyyd.de/0.2"
_EPISODE_SEARCH_URL = f"{_API_BASE}/search/episode"
_PODCAST_SEARCH_URL = f"{_API_BASE}/search/podcast"
# Canonical fyyd pages, used when a record omits its own page URL.
_EPISODE_PAGE_URL = "https://fyyd.de/episode/"
_PODCAST_PAGE_URL = "https://fyyd.de/podcast/"
# fyyd caps a single search request; keep the page small for agents.
_MAX_API_RESULTS = 50
# Characters of the episode/show description copied into the snippet.
_SNIPPET_DESCRIPTION_LENGTH = 200
# Placeholder duration strings fyyd uses when a length is unknown.
_UNKNOWN_DURATIONS = {"", "n/a", "unknown", "none", "0:00"}


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _int_or_none(value: object) -> int | None:
    """Return *value* as an int, or ``None`` when it is not an integer.

    Booleans are rejected (``True`` is an ``int`` in Python but never a
    meaningful id or count here), as are non-numeric strings.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lstrip("-").isdigit():
            return int(stripped)
    return None


class FyydProvider(BaseProvider):
    """Search podcast episodes — falling back to shows — via the fyyd API.

    Keyless.  Queries fyyd's episode search first and returns one hit per
    episode, carrying the description, audio enclosure URL, duration,
    season/episode numbers, publication date, artwork and fyyd episode page.
    When no episode matches, the show-level search runs instead so a
    programme's name resolves to the podcast itself.
    """

    name = "fyyd"
    description = (
        "Search podcast episodes and shows in the keyless fyyd podcast "
        "directory (episode title, description, audio enclosure URL, "
        "duration, season/episode numbers, publication date and artwork), "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["podcast", "media"]

    @staticmethod
    def _payload_items(payload: object) -> list[dict[str, Any]]:
        """Return the records of a fyyd JSON response, or an empty list."""
        if not isinstance(payload, dict) or payload.get("status") != 1:
            return []
        items = payload.get("data")
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    @staticmethod
    def _duration_label(item: dict[str, Any]) -> str:
        """Return a human-readable episode duration, e.g. ``1:00:05``.

        fyyd exposes the length both as integer seconds (``duration``) and as
        a preformatted string (``duration_string``).  Seconds are preferred;
        the string is used only when it carries a real value rather than one
        of fyyd's ``n/a`` placeholders.
        """
        seconds = _int_or_none(item.get("duration"))
        if seconds and seconds > 0:
            hours, remainder = divmod(seconds, 3600)
            minutes, secs = divmod(remainder, 60)
            if hours:
                return f"{hours}:{minutes:02d}:{secs:02d}"
            return f"{minutes}:{secs:02d}"
        label = _clean(item.get("duration_string"))
        return "" if label.lower() in _UNKNOWN_DURATIONS else label

    def _episode_result(
        self,
        item: dict[str, Any],
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw fyyd episode record."""
        title = _clean(item.get("title"))
        episode_id = _int_or_none(item.get("id"))
        fyyd_url = _clean(item.get("url_fyyd"))
        if not fyyd_url and episode_id is not None:
            fyyd_url = f"{_EPISODE_PAGE_URL}{episode_id}"
        page_url = _clean(item.get("url"))
        url = page_url or fyyd_url
        if not title or not url:
            return None

        description = _clean(item.get("description"))
        duration = self._duration_label(item)
        audio_url = _clean(item.get("enclosure"))
        season = _int_or_none(item.get("num_season")) or 0
        episode = _int_or_none(item.get("num_episode")) or 0

        snippet_parts: list[str] = []
        if description:
            snippet_parts.append(description[:_SNIPPET_DESCRIPTION_LENGTH])
        if season and episode:
            snippet_parts.append(f"S{season}E{episode}")
        elif episode:
            snippet_parts.append(f"Episode {episode}")
        if duration:
            snippet_parts.append(f"Duration: {duration}")
        if audio_url:
            snippet_parts.append("Audio available")

        return SearchResult(
            title=title,
            url=url,
            snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
            source="fyyd.de",
            rank=rank,
            provider=self.name,
            published_date=self._iso_date_prefix(_clean(item.get("pubdate"))),
            extra={
                "type": "episode",
                "episode_id": episode_id,
                "podcast_id": _int_or_none(item.get("podcast_id")),
                "description": description,
                "audio_url": audio_url or None,
                "content_type": _clean(item.get("content_type")) or None,
                "duration": duration or None,
                "duration_seconds": _int_or_none(item.get("duration")),
                "season": season or None,
                "episode": episode or None,
                "image_url": _clean(item.get("imgURL")) or None,
                "page_url": page_url or None,
                "fyyd_url": fyyd_url or None,
                "guid": _clean(item.get("guid")) or None,
            },
        )

    def _podcast_result(
        self,
        item: dict[str, Any],
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw fyyd podcast record."""
        title = _clean(item.get("title"))
        podcast_id = _int_or_none(item.get("id"))
        fyyd_url = _clean(item.get("url_fyyd"))
        if not fyyd_url and podcast_id is not None:
            fyyd_url = f"{_PODCAST_PAGE_URL}{podcast_id}"
        website = _clean(item.get("htmlURL"))
        url = website or fyyd_url
        if not title or not url:
            return None

        author = _clean(item.get("author"))
        language = _clean(item.get("language"))
        feed_url = _clean(item.get("xmlURL"))
        description = _clean(item.get("description")) or _clean(item.get("subtitle"))
        episode_count = _int_or_none(item.get("episode_count"))
        categories = item.get("categories")
        category_ids: list[int] = []
        if isinstance(categories, list):
            category_ids = [
                cid
                for cid in (_int_or_none(entry) for entry in categories)
                if cid is not None
            ]

        snippet_parts: list[str] = []
        if description:
            snippet_parts.append(description[:_SNIPPET_DESCRIPTION_LENGTH])
        if author:
            snippet_parts.append(f"Author: {author}")
        if language:
            snippet_parts.append(f"Language: {language}")
        if episode_count:
            snippet_parts.append(f"Episodes: {episode_count}")

        return SearchResult(
            title=title,
            url=url,
            snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
            source="fyyd.de",
            rank=rank,
            provider=self.name,
            published_date=self._iso_date_prefix(_clean(item.get("lastpub"))),
            extra={
                "type": "podcast",
                "podcast_id": podcast_id,
                "author": author or None,
                "language": language or None,
                "description": description,
                "episode_count": episode_count,
                "feed_url": feed_url or None,
                "website_url": website or None,
                "image_url": _clean(item.get("imgURL")) or None,
                "fyyd_url": fyyd_url or None,
                "categories": category_ids,
                "rank": _int_or_none(item.get("rank")),
                "last_published": _clean(item.get("lastpub")) or None,
            },
        )

    def _build_results(
        self,
        items: list[dict[str, Any]],
        limit: int,
        *,
        episodes: bool,
    ) -> list[SearchResult]:
        """Convert raw records into results, deduplicating by record id."""
        build = self._episode_result if episodes else self._podcast_result
        results: list[SearchResult] = []
        seen: set[object] = set()
        for item in items:
            if len(results) >= limit:
                break
            key = item.get("id")
            if key is not None:
                if key in seen:
                    continue
                seen.add(key)
            built = build(item, len(results) + 1)
            if built is None:
                continue
            results.append(built)
        return results

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search fyyd for podcast episodes matching *query*.

        A blank query performs no request.  When the episode search matches
        nothing the show-level search runs as a fallback, so the name of a
        programme still resolves to the podcast itself.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        async with self._client() as client:
            resp = await client.get(
                _EPISODE_SEARCH_URL,
                params={"term": cleaned, "count": limit},
            )
            resp.raise_for_status()
            episodes = self._build_results(
                self._payload_items(resp.json()),
                limit,
                episodes=True,
            )
            if episodes:
                return ProviderResult(results=episodes)

            resp = await client.get(
                _PODCAST_SEARCH_URL,
                params={"term": cleaned, "count": limit},
            )
            resp.raise_for_status()
            shows = self._build_results(
                self._payload_items(resp.json()),
                limit,
                episodes=False,
            )

        return ProviderResult(results=shows)
