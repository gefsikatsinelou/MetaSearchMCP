"""Search Qur'an verses by keyword via the keyless quran.com v4 API.

The Qur'an.com API (``api.quran.com/api/v4``) is a public JSON API that
needs no API key for its search endpoint.  A single request performs a
keyword search across the Qur'an's translations and returns the matching
verses::

    GET https://api.quran.com/api/v4/search?q=mercy&size=10&page=1

Each hit carries the ``verse_key`` (a ``surah:ayah`` reference such as
``2:255``), the Arabic ``text`` and a ``translations`` array whose entries
each hold the translated ``text`` (with ``<em>`` markers around matched
words), the translation ``name`` and its ``language_name``.

The provider surfaces each matched verse as its own result, titled by its
reference and linked to the corresponding quran.com verse page.  A query
with no matches returns an empty ``results`` array, which this provider
treats as an empty result set rather than an error.
"""

from __future__ import annotations

import html
import re
from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_ENDPOINT = "https://api.quran.com/api/v4/search"
_SOURCE = "quran.com"
# The search endpoint's own result cap; the provider never asks for more.
_MAX_API_RESULTS = 50
# quran.com serves one verse page per "surah/ayah" path.
_VERSE_URL = "https://quran.com/{surah}/{ayah}"
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _strip_markup(value: object) -> str:
    """Return cleaned text with any HTML tags (e.g. ``<em>``) removed."""
    text = html.unescape(_clean(value))
    return " ".join(_TAG_RE.sub("", text).split())


def _int_or_none(value: object) -> int | None:
    """Return an integer field, ignoring booleans and non-integer values."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _split_verse_key(verse_key: str) -> tuple[int | None, int | None]:
    """Split a ``surah:ayah`` reference into its two integer parts."""
    surah_text, _, ayah_text = verse_key.partition(":")
    if not surah_text.isdigit() or not ayah_text.isdigit():
        return None, None
    return int(surah_text), int(ayah_text)


class QuranProvider(BaseProvider):
    """Search Qur'an verses by keyword via the keyless quran.com API.

    Keyless.  The query is a keyword matched across the Qur'an's
    translations; each matching verse is returned with its ``surah:ayah``
    reference, Arabic text and translated text.
    """

    name = "quran"
    description = (
        "Search Qur'an verses by keyword (e.g. 'mercy' or 'patience') via the "
        "keyless quran.com v4 API. Each result carries the surah:ayah reference, "
        "the Arabic verse text and a translated verse text. No API key required."
    )
    tags: ClassVar[list[str]] = ["scripture", "religion", "reference"]

    @staticmethod
    def _verse_url(surah: int | None, ayah: int | None, query: str) -> str:
        """Return the quran.com verse URL, or the search URL as a fallback."""
        if surah is not None and ayah is not None:
            return _VERSE_URL.format(surah=surah, ayah=ayah)
        return f"{_ENDPOINT}?q={quote(query, safe='')}"

    @staticmethod
    def _translation(item: dict[str, Any]) -> dict[str, Any] | None:
        """Return the first usable translation entry, or ``None``."""
        translations = item.get("translations")
        if not isinstance(translations, list):
            return None
        for entry in translations:
            if isinstance(entry, dict) and _strip_markup(entry.get("text")):
                return entry
        return None

    def _build_result(
        self,
        item: dict[str, Any],
        rank: int,
        query: str,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a single verse, or ``None``."""
        verse_key = _clean(item.get("verse_key"))
        if not verse_key:
            return None

        surah, ayah = _split_verse_key(verse_key)
        translation = self._translation(item) or {}
        snippet = _strip_markup(translation.get("text"))

        return SearchResult(
            title=f"Qur'an {verse_key}",
            url=self._verse_url(surah, ayah, query),
            snippet=snippet[:MAX_SNIPPET_LENGTH],
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            extra={
                "verse_key": verse_key,
                "surah": surah,
                "ayah": ayah,
                "arabic": _clean(item.get("text")) or None,
                "translation": _clean(translation.get("name")) or None,
                "language": _clean(translation.get("language_name")) or None,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a quran.com search response into structured verse results.

        The service's own relevance order is preserved; records without a
        usable reference are skipped and any other payload shape yields an
        empty page.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        search = data.get("search")
        if not isinstance(search, dict):
            return ProviderResult(results=results)

        hits = search.get("results")
        if not isinstance(hits, list):
            return ProviderResult(results=results)

        query = _clean(search.get("query"))
        max_results = limit or self._max_results
        for item in hits:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            built = self._build_result(item, len(results) + 1, query)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the Qur'an for verses matching *query*.

        A blank query performs no request.  The keyword is matched across the
        Qur'an's translations and the service's own relevance order is kept.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _ENDPOINT,
                params={
                    "q": cleaned,
                    "size": limit,
                    "page": 1,
                    "language": self._language_code(params.language),
                },
            )
            resp.raise_for_status()
            data: object = resp.json()

        return self._parse(data, limit)
