"""Search the MyAnimeList anime database via the Jikan REST API.

MyAnimeList (MAL) is the largest community catalogue of anime, manga and
related media.  Its official API is not public, but the community-run
`Jikan <https://jikan.moe>`_ project exposes a free, keyless, read-only
mirror of the database whose search endpoint accepts a keyword::

    GET https://api.jikan.moe/v4/anime?q=QUERY&limit=N[&sfw=true]

The response is ``{"pagination": {...}, "data": [...]}``; ``pagination.items
.total`` holds the overall number of matches and each record carries the
canonical ``myanimelist.net`` URL, the titles in several languages, the media
type and source, release status and air dates, episode count, rating,
community score/rank/popularity/members/favourites, season and year,
studios/producers/licensors, genres, themes and demographics, a synopsis and
a cover image.

This complements the AniList, Kitsu and MangaDex providers with the canonical
MyAnimeList catalogue.  No API key is required; Jikan asks for a polite rate
limit of roughly 3 requests per second and 60 per minute.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_ENDPOINT = "https://api.jikan.moe/v4/anime"
_SOURCE = "myanimelist.net"
_PAGE_URL = "https://myanimelist.net/anime/"
# Jikan caps ``limit`` at 25 records per request.
_MAX_API_RESULTS = 25
# Synopses are long; keep a readable prefix in ``extra``.
_MAX_DESCRIPTION_LENGTH = 500
# Genres/studios listed in a snippet before closing the list.
_MAX_SNIPPET_GENRES = 4
_MAX_SNIPPET_STUDIOS = 3


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _int(value: object) -> int | None:
    """Return an integer field, ignoring booleans and non-integer values."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _float(value: object) -> float | None:
    """Return a numeric field as a float, ignoring booleans and strings."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _strings(value: object) -> list[str]:
    """Return the non-empty string entries of a list-valued field."""
    if not isinstance(value, list):
        return []
    return [text for entry in value if (text := _clean(entry))]


def _names(value: object) -> list[str]:
    """Return the ``name`` of each mapping in a Jikan entity list, in order."""
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        name = _clean(entry.get("name"))
        if name:
            names.append(name)
    return names


def _duration_date(value: object) -> str | None:
    """Return the ``YYYY-MM-DD`` prefix of an aired ``from`` timestamp."""
    if not isinstance(value, dict):
        return None
    raw = _clean(value.get("from"))
    if not raw:
        return None
    return raw[:10] or None


def _season(value: object) -> str | None:
    """Return a record's season as e.g. ``Fall 2002``, if known."""
    season = _clean(value.get("season")).title() if isinstance(value, dict) else ""
    year = _int(value.get("year")) if isinstance(value, dict) else None
    parts = [part for part in (season, str(year) if year is not None else "") if part]
    return " ".join(parts) or None


class JikanProvider(BaseProvider):
    """Search anime records in the MyAnimeList database via Jikan.

    Keyless.  A single request matches *query* against anime titles with
    MyAnimeList's own relevance order and returns hits, each carrying its
    titles, type, source, status, air dates, episode count, rating, score,
    rank, popularity, members, favourites, season, studios, genres, synopsis
    and cover image, plus a link to the canonical ``myanimelist.net`` page.
    """

    name = "jikan"
    description = (
        "Search MyAnimeList (via the keyless Jikan API) for anime by keyword: "
        "type, source, status, air dates, episode count, rating, community "
        "score, rank, popularity, members, season, studios, genres, synopsis "
        "and cover image. No API key required."
    )
    tags: ClassVar[list[str]] = ["anime", "media"]

    @staticmethod
    def _title(item: dict[str, Any]) -> str:
        """Return the best available title (English, default, then Japanese)."""
        title = _clean(item.get("title_english")) or _clean(item.get("title"))
        if title:
            return title
        titles = item.get("titles")
        if isinstance(titles, list):
            for entry in titles:
                if isinstance(entry, dict) and _clean(entry.get("title")):
                    return _clean(entry.get("title"))
        return _clean(item.get("title_japanese"))

    @staticmethod
    def _counts(episodes: int | None) -> str:
        """Return an episode-count phrase such as ``24 episodes``."""
        if episodes is None:
            return ""
        return f"{episodes} episode{'s' if episodes != 1 else ''}"

    def _snippet(self, item: dict[str, Any]) -> str:
        """Compose the snippet for a single anime record."""
        parts: list[str] = []

        media_type = _clean(item.get("type"))
        if media_type:
            parts.append(media_type)

        status = _clean(item.get("status"))
        if status:
            parts.append(status)

        season = _season(item)
        if season:
            parts.append(season)

        counts = self._counts(_int(item.get("episodes")))
        if counts:
            parts.append(counts)

        score = _float(item.get("score"))
        if score is not None:
            parts.append(f"score {score:.2f}/10")

        rank = _int(item.get("rank"))
        if rank is not None:
            parts.append(f"rank #{rank}")

        members = _int(item.get("members"))
        if members is not None:
            parts.append(f"{members:,} members")

        genres = _names(item.get("genres"))
        if genres:
            parts.append(", ".join(genres[:_MAX_SNIPPET_GENRES]))

        studios = _names(item.get("studios"))
        if studios:
            parts.append("by " + ", ".join(studios[:_MAX_SNIPPET_STUDIOS]))

        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        total: int | None,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a Jikan anime record."""
        title = self._title(item)
        if not title:
            return None

        mal_id = _int(item.get("mal_id"))
        url = _clean(item.get("url"))
        if not url and mal_id is not None:
            url = f"{_PAGE_URL}{mal_id}"
        if not url:
            return None

        images = item.get("images")
        image = ""
        if isinstance(images, dict):
            jpg = images.get("jpg")
            if isinstance(jpg, dict):
                image = _clean(jpg.get("large_image_url")) or _clean(
                    jpg.get("image_url"),
                )

        synopsis = _clean(item.get("synopsis"))[:_MAX_DESCRIPTION_LENGTH]
        airing = item.get("airing")

        return SearchResult(
            title=title,
            url=url,
            snippet=self._snippet(item),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            published_date=_duration_date(item.get("aired")),
            extra={
                "mal_id": mal_id,
                "title_english": _clean(item.get("title_english")) or None,
                "title_japanese": _clean(item.get("title_japanese")) or None,
                "title_synonyms": _strings(item.get("title_synonyms")),
                "type": _clean(item.get("type")) or None,
                "source": _clean(item.get("source")) or None,
                "episodes": _int(item.get("episodes")),
                "status": _clean(item.get("status")) or None,
                "airing": airing if isinstance(airing, bool) else None,
                "aired": (
                    _clean(item["aired"].get("string"))
                    if isinstance(item.get("aired"), dict)
                    else ""
                )
                or None,
                "duration": _clean(item.get("duration")) or None,
                "rating": _clean(item.get("rating")) or None,
                "score": _float(item.get("score")),
                "scored_by": _int(item.get("scored_by")),
                "rank": _int(item.get("rank")),
                "popularity": _int(item.get("popularity")),
                "members": _int(item.get("members")),
                "favourites": _int(item.get("favorites")),
                "season": _clean(item.get("season")) or None,
                "year": _int(item.get("year")),
                "studios": _names(item.get("studios")),
                "producers": _names(item.get("producers")),
                "licensors": _names(item.get("licensors")),
                "genres": _names(item.get("genres")),
                "themes": _names(item.get("themes")),
                "demographics": _names(item.get("demographics")),
                "synopsis": synopsis or None,
                "image_url": image or None,
                "total_results": total,
            },
        )

    def _parse(self, data: object, limit: int) -> ProviderResult:
        """Parse a Jikan search response, preserving MyAnimeList's order."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        items = data.get("data")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        pagination = data.get("pagination")
        total = None
        if isinstance(pagination, dict):
            counts = pagination.get("items")
            if isinstance(counts, dict):
                total = _int(counts.get("total"))

        for item in items:
            if len(results) >= limit:
                break
            if not isinstance(item, dict):
                continue
            built = self._build_result(item, total, len(results) + 1)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search MyAnimeList for *query*.

        A blank query performs no request.  MyAnimeList's own relevance order
        is preserved.  When ``params.safe_search`` is set, the ``sfw`` filter
        is applied so that adult entries are excluded.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        request_params: dict[str, Any] = {"q": cleaned, "limit": limit}
        if params.safe_search:
            request_params["sfw"] = "true"

        async with self._client() as client:
            resp = await client.get(_ENDPOINT, params=request_params)
            resp.raise_for_status()
            data: object = resp.json()

        return self._parse(data, limit)
