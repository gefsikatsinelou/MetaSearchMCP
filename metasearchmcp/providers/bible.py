"""Search Bible passages by reference via the keyless bible-api.com service.

bible-api.com exposes a small, public JSON API that resolves a Bible
*reference* — a book, a book with a chapter, or a book with a chapter and
verse range — to the matching verses.  No API key is required::

    GET https://bible-api.com/john%203:16?translation=web

The reference is carried in the URL path and accepts forms such as
``john 3:16`` (a verse), ``psalms 23`` (a whole chapter) or
``1 corinthians 13:4-7`` (a verse range).  A successful response carries
the resolved ``reference``, an optional ``translation_id`` /
``translation_name`` and a ``verses`` array whose entries each hold the
``book_id``, ``book_name``, ``chapter``, ``verse`` and verse ``text``.

Each verse is surfaced as its own result, linked to the bible-api.com
record for that reference.  The provider requests the public-domain World
English Bible (``web``) so the returned text is freely redistributable and
stable over time.  References the service cannot resolve return HTTP 404,
which this provider treats as an empty result set rather than an error.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_ENDPOINT = "https://bible-api.com"
_SOURCE = "bible-api.com"
# Public-domain World English Bible: pinned so returned text is stable.
_TRANSLATION = "web"


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _int_or_none(value: object) -> int | None:
    """Return an integer field, ignoring booleans and non-integer values."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


class BibleProvider(BaseProvider):
    """Look up Bible verses by reference via the keyless bible-api.com API.

    Keyless.  The query is a scripture reference such as ``john 3:16``,
    ``romans 8:28`` or a whole chapter like ``psalms 23``; each matching
    verse is returned with its book, chapter, verse number and text.
    """

    name = "bible"
    description = (
        "Look up Bible passages by reference (e.g. 'john 3:16' or 'psalms 23') "
        "via the keyless bible-api.com service. Each verse is returned with its "
        "book, chapter, verse number and World English Bible text. No API key "
        "required."
    )
    tags: ClassVar[list[str]] = ["scripture", "religion", "reference"]

    @staticmethod
    def _verse_url(reference: str) -> str:
        """Return the bible-api.com record URL for a verse *reference*."""
        return f"{_ENDPOINT}/{quote(reference, safe='')}"

    @staticmethod
    def _reference(item: dict[str, Any]) -> str:
        """Compose a canonical 'Book chapter:verse' reference for a verse."""
        book = _clean(item.get("book_name")) or _clean(item.get("book_id"))
        chapter = _int_or_none(item.get("chapter"))
        verse = _int_or_none(item.get("verse"))
        if book and chapter is not None and verse is not None:
            return f"{book} {chapter}:{verse}"
        return book

    def _build_result(
        self,
        item: dict[str, Any],
        rank: int,
        translation: str | None,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a single verse, or ``None``."""
        reference = self._reference(item)
        if not reference:
            return None

        text = _clean(item.get("text"))
        return SearchResult(
            title=reference,
            url=self._verse_url(reference),
            snippet=text[:MAX_SNIPPET_LENGTH],
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            extra={
                "book_id": _clean(item.get("book_id")) or None,
                "book": _clean(item.get("book_name")) or None,
                "chapter": _int_or_none(item.get("chapter")),
                "verse": _int_or_none(item.get("verse")),
                "translation": translation,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a bible-api.com response into structured verse results.

        The response's own verse order is preserved; records without a
        usable reference are skipped and any other payload shape yields an
        empty page.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        verses = data.get("verses")
        if not isinstance(verses, list):
            return ProviderResult(results=results)

        translation = _clean(data.get("translation_id")) or None
        max_results = limit or self._max_results
        for item in verses:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            built = self._build_result(item, len(results) + 1, translation)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Resolve *query* as a Bible reference and return its verses.

        A blank query performs no request.  References the service cannot
        resolve (HTTP 404) yield an empty result set rather than an error.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results)
        url = f"{_ENDPOINT}/{quote(cleaned)}"
        async with self._client() as client:
            resp = await client.get(url, params={"translation": _TRANSLATION})
            if resp.status_code == 404:
                return ProviderResult(results=[])
            resp.raise_for_status()
            data: object = resp.json()

        return self._parse(data, limit)
