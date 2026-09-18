"""Search the MangaDex manga catalogue.

MangaDex is a community-run, keyless manga database whose public REST API
supports title search::

    GET https://api.mangadex.org/manga
        ?title=<query>&limit=N&order[relevance]=desc
        &includes[]=cover_art&includes[]=author&includes[]=artist

The keyword is matched against manga titles — including the alternate titles
MangaDex keeps — with MangaDex's own relevance ranking, and the returned
order is preserved.  A single request yields up to ``limit`` records plus the
total number of matches in the ``total`` field, so — like the AniList and
Kitsu providers — no per-record follow-up request is needed.

Each record carries the title in every language MangaDex knows, alternate
titles, a synopsis, the publication status, year, content rating, publication
demographic, chapter and volume counts, genres and themes, authors/artists,
the cover image and the canonical ``mangadex.org`` page.

No API key or registration is required.  MangaDex only returns ``safe``
records unless other content ratings are requested explicitly, so a safe
search asks for ``safe`` and ``suggestive`` records while an unsafe search
also includes ``erotica`` and ``pornographic`` ones.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_ENDPOINT = "https://api.mangadex.org/manga"
_SOURCE = "mangadex.org"
# Canonical page of a manga, keyed by its MangaDex UUID.
_TITLE_URL = "https://mangadex.org/title/"
# Cover art files live under a per-manga directory; a ``.256.jpg`` suffix
# requests the small thumbnail rather than the full-size scan.
_COVER_URL_BASE = "https://uploads.mangadex.org/covers/"
_COVER_THUMBNAIL_SUFFIX = ".256.jpg"
# MangaDex caps ``limit`` at 100 records per request.
_MAX_API_RESULTS = 100
# Synopses are long and often carry release notes; keep a readable prefix.
_MAX_DESCRIPTION_LENGTH = 500
# Maximum number of tags listed in a snippet.
_MAX_SNIPPET_TAGS = 4
# Maximum number of translated languages listed in ``extra``.
_MAX_TRANSLATED_LANGUAGES = 10
# Content ratings.  MangaDex omits everything above ``safe`` unless asked.
_SAFE_RATINGS = ("safe", "suggestive")
_ALL_RATINGS = ("safe", "suggestive", "erotica", "pornographic")


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _localized(value: object, preferred: tuple[str, ...] = ("en",)) -> str:
    """Return the best text of a MangaDex localised field.

    Titles and synopses arrive as ``language code -> text`` maps; the
    languages in *preferred* win, and any other language is used as a
    fallback so that a record without English text still yields a string.
    """
    if not isinstance(value, dict):
        return ""
    for code in preferred:
        text = _clean(value.get(code))
        if text:
            return text
    for text in value.values():
        cleaned = _clean(text)
        if cleaned:
            return cleaned
    return ""


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


def _label(value: object) -> str:
    """Render a MangaDex enum field (``shoujo``, ``suggestive``) for display."""
    return _clean(value).replace("_", " ").title()


def _title_map(attributes: dict[str, Any]) -> dict[str, str]:
    """Return the non-empty primary titles of a manga by language code."""
    primary = attributes.get("title")
    if not isinstance(primary, dict):
        return {}
    titles: dict[str, str] = {}
    for code, value in primary.items():
        text = _clean(value)
        if text and isinstance(code, str):
            titles[code] = text
    return titles


def _alt_titles(attributes: dict[str, Any]) -> list[str]:
    """Return the deduplicated alternate titles of a manga, in listed order."""
    entries = attributes.get("altTitles")
    if not isinstance(entries, list):
        return []
    titles: list[str] = []
    for entry in entries:
        text = _localized(entry)
        if text and text not in titles:
            titles.append(text)
    return titles


def _title_candidates(attributes: dict[str, Any]) -> list[str]:
    """Return a manga's titles in display preference order.

    English titles are preferred, whether they come from the primary title
    map or from the alternate titles, followed by every other language in the
    order MangaDex lists it.
    """
    maps: list[dict[str, Any]] = []
    primary = _title_map(attributes)
    if primary:
        maps.append(primary)
    alternate = attributes.get("altTitles")
    if isinstance(alternate, list):
        maps.extend(entry for entry in alternate if isinstance(entry, dict))

    preferred: list[str] = []
    fallback: list[str] = []
    for mapping in maps:
        for code, value in mapping.items():
            text = _clean(value)
            if not text or not isinstance(code, str):
                continue
            if text in preferred or text in fallback:
                continue
            target = preferred if code.lower().startswith("en") else fallback
            target.append(text)
    return preferred + fallback


def _relation_names(item: dict[str, Any], kind: str) -> list[str]:
    """Return the names of a manga's related entities of the given type."""
    relationships = item.get("relationships")
    if not isinstance(relationships, list):
        return []
    names: list[str] = []
    for relation in relationships:
        if not isinstance(relation, dict) or _clean(relation.get("type")) != kind:
            continue
        attributes = relation.get("attributes")
        if not isinstance(attributes, dict):
            continue
        name = _clean(attributes.get("name"))
        if name and name not in names:
            names.append(name)
    return names


def _cover(item: dict[str, Any], manga_id: str) -> str:
    """Return the cover-art thumbnail URL of a manga, if one is attached."""
    relationships = item.get("relationships")
    if not isinstance(relationships, list):
        return ""
    for relation in relationships:
        if not isinstance(relation, dict):
            continue
        if _clean(relation.get("type")) != "cover_art":
            continue
        attributes = relation.get("attributes")
        if not isinstance(attributes, dict):
            continue
        file_name = _clean(attributes.get("fileName"))
        if file_name:
            return f"{_COVER_URL_BASE}{manga_id}/{file_name}{_COVER_THUMBNAIL_SUFFIX}"
    return ""


def _tags(value: object) -> list[str]:
    """Return the genre, theme and format names attached to a manga."""
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        attributes = entry.get("attributes")
        if not isinstance(attributes, dict):
            continue
        name = _localized(attributes.get("name"))
        if name and name not in names:
            names.append(name)
    return names


def _count(value: object, unit: str) -> str:
    """Render a chapter or volume count such as ``11 chapters``."""
    cleaned = _clean(value)
    if not cleaned:
        return ""
    return f"{cleaned} {unit if cleaned == '1' else unit + 's'}"


class MangaDexProvider(BaseProvider):
    """Search manga records in the MangaDex catalogue.

    Keyless.  A single request matches *query* against MangaDex's titles and
    alternate titles and returns manga hits in relevance order, each carrying
    its titles, synopsis, status, year, content rating, demographic,
    chapter/volume counts, tags, authors/artists, cover image and canonical
    page URL.
    """

    name = "mangadex"
    description = (
        "Search MangaDex, the community manga database: titles by keyword "
        "including alternate titles, with synopsis, status, year, content "
        "rating, demographic, chapter/volume counts, genres, authors/artists "
        "and cover image. No API key required."
    )
    tags: ClassVar[list[str]] = ["manga", "media"]

    def _snippet(self, attributes: dict[str, Any], item: dict[str, Any]) -> str:
        """Compose the snippet for a single manga record.

        Status, year, chapter/volume counts, demographic, non-safe content
        rating, genres and creators are combined so that a result stays
        informative even when the caller does not look at ``extra``.
        """
        parts: list[str] = []

        status = _label(attributes.get("status"))
        if status:
            parts.append(status)

        year = _int(attributes.get("year"))
        if year is not None:
            parts.append(str(year))

        for key, unit in (("lastChapter", "chapter"), ("lastVolume", "volume")):
            count = _count(attributes.get(key), unit)
            if count:
                parts.append(count)

        demographic = _label(attributes.get("publicationDemographic"))
        if demographic:
            parts.append(demographic)

        rating = _clean(attributes.get("contentRating"))
        if rating and rating not in _SAFE_RATINGS:
            parts.append(_label(rating))

        tags = _tags(attributes.get("tags"))
        if tags:
            parts.append(", ".join(tags[:_MAX_SNIPPET_TAGS]))

        authors = _relation_names(item, "author")
        artists = _relation_names(item, "artist")
        creators = [name for name in authors if name not in artists] + artists
        if creators:
            parts.append("by " + ", ".join(creators))

        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        total: int | None,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a MangaDex manga record."""
        manga_id = _clean(item.get("id"))
        attributes = item.get("attributes")
        if not manga_id or not isinstance(attributes, dict):
            return None

        candidates = _title_candidates(attributes)
        if not candidates:
            return None

        year = _int(attributes.get("year"))
        description = _localized(attributes.get("description"))[
            :_MAX_DESCRIPTION_LENGTH
        ]
        languages = _strings(attributes.get("availableTranslatedLanguages"))
        links = attributes.get("links")

        return SearchResult(
            title=candidates[0],
            url=f"{_TITLE_URL}{manga_id}",
            snippet=self._snippet(attributes, item),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            published_date=str(year) if year is not None else None,
            extra={
                "mangadex_id": manga_id,
                "titles": _title_map(attributes),
                "alt_titles": _alt_titles(attributes),
                "description": description or None,
                "status": _clean(attributes.get("status")) or None,
                "year": year,
                "content_rating": _clean(attributes.get("contentRating")) or None,
                "publication_demographic": (
                    _clean(attributes.get("publicationDemographic")) or None
                ),
                "last_chapter": _clean(attributes.get("lastChapter")) or None,
                "last_volume": _clean(attributes.get("lastVolume")) or None,
                "original_language": (
                    _clean(attributes.get("originalLanguage")) or None
                ),
                "authors": _relation_names(item, "author"),
                "artists": _relation_names(item, "artist"),
                "tags": _tags(attributes.get("tags")),
                "available_translated_languages": languages[:_MAX_TRANSLATED_LANGUAGES],
                "cover_image": _cover(item, manga_id) or None,
                "links": links if isinstance(links, dict) else None,
                "total_results": total,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a MangaDex manga response into structured results.

        MangaDex's own relevance order is preserved; any other payload shape
        yields an empty page.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        records = data.get("data")
        if not isinstance(records, list):
            return ProviderResult(results=results)

        total = _int(data.get("total"))
        max_results = limit or self._max_results
        for item in records:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            built = self._build_result(item, total, len(results) + 1)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search MangaDex manga titles for *query*.

        A blank query performs no request.  MangaDex matches the keyword
        against manga titles and alternate titles and returns hits in its own
        relevance order.  When ``params.safe_search`` is set only ``safe`` and
        ``suggestive`` records are requested; otherwise ``erotica`` and
        ``pornographic`` records are included as well.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        ratings = _SAFE_RATINGS if params.safe_search else _ALL_RATINGS
        # List values are expanded by httpx into repeated query parameters,
        # which is how MangaDex expects its ``includes[]``/``contentRating[]``.
        request_params: dict[str, Any] = {
            "title": cleaned,
            "limit": limit,
            "order[relevance]": "desc",
            "includes[]": ["cover_art", "author", "artist"],
            "contentRating[]": list(ratings),
        }
        async with self._client() as client:
            resp = await client.get(_ENDPOINT, params=request_params)
            resp.raise_for_status()
            data: object = resp.json()

        return self._parse(data, limit)
