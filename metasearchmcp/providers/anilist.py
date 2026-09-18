"""Search the AniList anime and manga database.

AniList is a community-maintained catalogue of anime, manga, light novels
and related media whose public GraphQL endpoint is keyless::

    POST https://graphql.anilist.co
    {"query": "...", "variables": {"search": "<query>", "perPage": N}}

The keyword is matched against media titles and synonyms with AniList's own
``SEARCH_MATCH`` relevance sort, and the returned order is preserved.  A
single request yields up to ``perPage`` records plus the total number of
matches in ``Page.pageInfo.total`` (which AniList caps at 5000), so — like
the Kitsu and MusicBrainz providers — no per-record follow-up request is
needed.

Each record carries the title in romaji, English and Japanese, a synopsis,
the media type (anime or manga), format, release status, season, partial
dates, episode/chapter/volume counts, genres, community scores, popularity,
the main animation studio, cover image and the canonical ``anilist.co``
page.

No API key or registration is required; AniList asks for a polite rate
limit of roughly 30 requests per minute.
"""

from __future__ import annotations

import html
import re
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_ENDPOINT = "https://graphql.anilist.co"
_SOURCE = "anilist.co"
# AniList caps ``perPage`` at 50 records per request.
_MAX_API_RESULTS = 50
# Synopses are long HTML-flavoured texts; keep a readable prefix in ``extra``.
_MAX_DESCRIPTION_LENGTH = 500
# Maximum number of studios listed in a snippet.
_MAX_SNIPPET_STUDIOS = 3
# Fallback page URLs for records that do not carry an explicit ``siteUrl``.
_ANIME_URL = "https://anilist.co/anime/"
_MANGA_URL = "https://anilist.co/manga/"

_QUERY = """
query ($search: String, $page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { total }
    media(search: $search, sort: SEARCH_MATCH) {
      id
      idMal
      type
      format
      status
      season
      seasonYear
      title { romaji english native }
      description(asHtml: false)
      startDate { year month day }
      endDate { year }
      episodes
      chapters
      volumes
      duration
      genres
      averageScore
      meanScore
      popularity
      favourites
      isAdult
      siteUrl
      coverImage { large }
      studios(isMain: true) { nodes { name } }
      countryOfOrigin
      source
    }
  }
}
"""

_TAG_RE = re.compile(r"<[^>]+>")
# Only line-break tags become spaces; other tags are dropped in place so
# that punctuation keeps sitting next to the word it belongs to.
_BREAK_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)

# Media formats use fixed acronyms that title-casing would mangle ("TV").
_FORMAT_LABELS = {
    "TV": "TV",
    "TV_SHORT": "TV Short",
    "MOVIE": "Movie",
    "SPECIAL": "Special",
    "OVA": "OVA",
    "ONA": "ONA",
    "MUSIC": "Music",
    "MANGA": "Manga",
    "NOVEL": "Novel",
    "ONE_SHOT": "One Shot",
}


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _text(value: object) -> str:
    """Return a whitespace-collapsed, tag-free rendering of an HTML field.

    Line breaks are turned into spaces so that the text either side of a
    break does not run together; all other tags are simply dropped.
    """
    raw = value if isinstance(value, str) else ""
    if not raw:
        return ""
    spaced = _BREAK_RE.sub(" ", raw)
    return " ".join(html.unescape(_TAG_RE.sub("", spaced)).split())


def _int(value: object) -> int | None:
    """Return an integer field, ignoring booleans and non-integer values."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _strings(value: object) -> list[str]:
    """Return the non-empty string entries of a list-valued field."""
    if not isinstance(value, (list, tuple)):
        return []
    return [text for entry in value if (text := _clean(entry))]


def _titles(value: object) -> dict[str, str]:
    """Return the non-empty romaji/english/native titles of a media record."""
    if not isinstance(value, dict):
        return {}
    titles: dict[str, str] = {}
    for key in ("romaji", "english", "native"):
        text = _clean(value.get(key))
        if text:
            titles[key] = text
    return titles


def _date(value: object) -> str | None:
    """Render an AniList partial date as the longest available ISO prefix.

    AniList dates only carry the parts the editors know, so a record may
    expose a full ``YYYY-MM-DD`` date, only ``YYYY-MM`` or just ``YYYY``.
    Unknown dates (no year) render as ``None``.
    """
    if not isinstance(value, dict):
        return None
    year = _int(value.get("year"))
    if year is None:
        return None
    month = _int(value.get("month"))
    day = _int(value.get("day"))
    if month is None:
        return f"{year:04d}"
    if day is None:
        return f"{year:04d}-{month:02d}"
    return f"{year:04d}-{month:02d}-{day:02d}"


def _studios(value: object) -> list[str]:
    """Return the names of a media record's main studios, in listed order."""
    nodes = value.get("nodes") if isinstance(value, dict) else None
    if not isinstance(nodes, list):
        return []
    names: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        name = _clean(node.get("name"))
        if name:
            names.append(name)
    return names


def _cover(value: object) -> str:
    """Return the large cover image URL of a media record, if any."""
    if not isinstance(value, dict):
        return ""
    return _clean(value.get("large"))


def _format_label(value: object) -> str:
    """Return the display label of an AniList media format.

    Formats are fixed identifiers such as ``TV`` or ``ONE_SHOT``; acronyms
    are kept as-is and unknown values fall back to title case.
    """
    cleaned = _clean(value)
    if not cleaned:
        return ""
    return _FORMAT_LABELS.get(cleaned.upper(), cleaned.replace("_", " ").title())


def _season(item: dict[str, Any]) -> str | None:
    """Return a record's season as e.g. ``FALL 1998``, if known."""
    name = _clean(item.get("season")).title()
    year = _int(item.get("seasonYear"))
    parts = [part for part in (name, str(year) if year is not None else "") if part]
    return " ".join(parts) or None


class AniListProvider(BaseProvider):
    """Search anime and manga records in the AniList database.

    Keyless.  A single GraphQL request matches *query* against AniList's
    titles and synonyms and returns anime, manga and light-novel hits in
    relevance order, each carrying its titles, synopsis, type, format,
    status, dates, episode/chapter counts, genres, scores, popularity,
    studio, cover image and canonical page URL.
    """

    name = "anilist"
    description = (
        "Search AniList, the community anime and manga database: media by "
        "keyword across anime, manga and light novels, with synopsis, format, "
        "release status, genres, community scores, popularity, studio and "
        "cover image. No API key required."
    )
    tags: ClassVar[list[str]] = ["anime", "manga", "media"]

    @staticmethod
    def _page_url(item: dict[str, Any], media_id: int | None) -> str:
        """Return the canonical AniList page URL for a media record.

        The API-provided ``siteUrl`` is preferred; records without one are
        linked through the id-based media path as a fallback.
        """
        url = _clean(item.get("siteUrl"))
        if url:
            return url
        if media_id is None:
            return ""
        base = _MANGA_URL if _clean(item.get("type")).upper() == "MANGA" else _ANIME_URL
        return f"{base}{media_id}"

    @staticmethod
    def _label(item: dict[str, Any]) -> str:
        """Return a short media label such as ``Anime TV`` or ``Manga``."""
        media_type = _clean(item.get("type")).title()
        media_format = _format_label(_clean(item.get("format")))
        if media_type and media_format and media_format != media_type:
            return f"{media_type} {media_format}"
        return media_type or media_format

    @staticmethod
    def _counts(item: dict[str, Any]) -> list[str]:
        """Return the unit-count phrases (episodes/chapters/volumes)."""
        units = (
            ("episodes", "episode"),
            ("chapters", "chapter"),
            ("volumes", "volume"),
        )
        parts: list[str] = []
        for key, unit in units:
            value = _int(item.get(key))
            if value is None:
                continue
            parts.append(f"{value} {unit}{'s' if value != 1 else ''}")
        return parts

    def _snippet(self, item: dict[str, Any]) -> str:
        """Compose the snippet for a single media record.

        Media label, status, start year, unit counts, genres, score,
        popularity and main studio are combined so that a result stays
        informative even when the caller does not look at ``extra``.
        """
        parts: list[str] = []
        label = self._label(item)
        if label:
            parts.append(label)

        status = _clean(item.get("status")).replace("_", " ").title()
        if status:
            parts.append(status)

        start = _date(item.get("startDate"))
        if start:
            parts.append(start[:4])

        parts.extend(self._counts(item))

        genres = _strings(item.get("genres"))
        if genres:
            parts.append(", ".join(genres[:4]))

        score = _int(item.get("averageScore"))
        if score is not None:
            parts.append(f"score {score}/100")

        popularity = _int(item.get("popularity"))
        if popularity is not None:
            parts.append(f"{popularity} AniList users")

        studios = _studios(item.get("studios"))
        if studios:
            parts.append("by " + ", ".join(studios[:_MAX_SNIPPET_STUDIOS]))

        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        total: int | None,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from an AniList media record."""
        titles = _titles(item.get("title"))
        title = titles.get("english") or titles.get("romaji") or titles.get("native")
        if not title:
            return None

        media_id = _int(item.get("id"))
        url = self._page_url(item, media_id)
        if not url:
            return None

        is_adult = item.get("isAdult")
        studios = _studios(item.get("studios"))
        description = _text(item.get("description"))[:_MAX_DESCRIPTION_LENGTH]

        return SearchResult(
            title=title,
            url=url,
            snippet=self._snippet(item),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            published_date=_date(item.get("startDate")),
            extra={
                "anilist_id": media_id,
                "mal_id": _int(item.get("idMal")),
                "media_type": _clean(item.get("type")) or None,
                "format": _clean(item.get("format")) or None,
                "status": _clean(item.get("status")) or None,
                "season": _season(item),
                "titles": titles,
                "description": description or None,
                "genres": _strings(item.get("genres")),
                "average_score": _int(item.get("averageScore")),
                "mean_score": _int(item.get("meanScore")),
                "popularity": _int(item.get("popularity")),
                "favourites": _int(item.get("favourites")),
                "episodes": _int(item.get("episodes")),
                "chapters": _int(item.get("chapters")),
                "volumes": _int(item.get("volumes")),
                "duration_minutes": _int(item.get("duration")),
                "start_date": _date(item.get("startDate")),
                "end_date": _date(item.get("endDate")),
                "studios": studios,
                "country_of_origin": _clean(item.get("countryOfOrigin")) or None,
                "source": _clean(item.get("source")) or None,
                "cover_image": _cover(item.get("coverImage")) or None,
                "is_adult": is_adult if isinstance(is_adult, bool) else None,
                "total_results": total,
            },
        )

    def _parse(
        self,
        data: object,
        limit: int | None = None,
        *,
        include_adult: bool = True,
    ) -> ProviderResult:
        """Parse an AniList GraphQL response into structured results.

        AniList's own relevance order is preserved.  When *include_adult* is
        false, records flagged as adult are dropped; any other payload shape
        yields an empty page.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        payload = data.get("data")
        if not isinstance(payload, dict):
            return ProviderResult(results=results)
        page = payload.get("Page")
        if not isinstance(page, dict):
            return ProviderResult(results=results)
        media = page.get("media")
        if not isinstance(media, list):
            return ProviderResult(results=results)

        page_info = page.get("pageInfo")
        total = _int(page_info.get("total")) if isinstance(page_info, dict) else None

        max_results = limit or self._max_results
        for item in media:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            if not include_adult and item.get("isAdult") is True:
                continue
            built = self._build_result(item, total, len(results) + 1)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search AniList media for *query*.

        A blank query performs no request.  AniList matches the keyword
        against media titles and synonyms and returns anime, manga and
        light-novel hits interleaved in relevance order.  When
        ``params.safe_search`` is set, records flagged as adult are dropped.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.post(
                _ENDPOINT,
                json={
                    "query": _QUERY,
                    "variables": {"search": cleaned, "page": 1, "perPage": limit},
                },
            )
            resp.raise_for_status()
            data: object = resp.json()

        return self._parse(data, limit, include_adult=not params.safe_search)
