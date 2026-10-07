"""LibriVox audiobook search via the public, keyless LibriVox API.

LibriVox (librivox.org) is a volunteer project that produces free public-domain
audiobooks from works in the public domain (largely Project Gutenberg texts).
It exposes a keyless, read-only JSON feed that supports full-text keyword
search across the catalogue::

    GET https://librivox.org/api/feed/audiobooks/?q=QUERY&format=json&limit=N

The response is ``{"books": [...]}`` (or ``{"error": "..."}`` when nothing
matches).  Each record carries the title, one or more authors with birth/death
years, a (HTML) description, the language, the copyright year, the number of
audio sections, the total running time, the canonical LibriVox page URL, the
Project Gutenberg text source, an RSS feed, a zip download and the archive.org
origin.  No API key or authentication is required.

This complements the Project Gutenberg (Gutendex) ebook provider with the
audiobook editions of the same public-domain literature.
"""

from __future__ import annotations

import html
import re
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_ENDPOINT = "https://librivox.org/api/feed/audiobooks/"
_SOURCE = "librivox.org"
# LibriVox returns at most 50 audiobooks per request.
_MAX_API_RESULTS = 50
# Descriptions arrive as HTML; keep a readable prefix in ``extra``.
_MAX_DESCRIPTION_LENGTH = 500
# Authors listed in a snippet before truncating the list.
_MAX_SNIPPET_AUTHORS = 5

# Matches an HTML/XML tag so it can be stripped from free-text fields.
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _strip_html(value: object) -> str:
    """Return *value* as plain text with HTML tags removed and entities decoded."""
    text = _clean(value)
    if not text:
        return ""
    return _clean(html.unescape(_TAG_RE.sub(" ", text)))


def _author_names(value: object) -> list[str]:
    """Return ``"First Last"`` author names from the API's author-dict list."""
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for author in value:
        if not isinstance(author, dict):
            continue
        first = _clean(author.get("first_name"))
        last = _clean(author.get("last_name"))
        name = f"{first} {last}".strip()
        if name and name not in names:
            names.append(name)
    return names


class LibriVoxProvider(BaseProvider):
    """Search free public-domain audiobooks in the LibriVox catalogue.

    Keyless.  A single request runs a full-text keyword search across the
    catalogue and returns hits, each carrying its authors (with birth/death
    years), language, copyright year, section count, total running time, a
    short description and links to the canonical LibriVox page, the Project
    Gutenberg source text, the RSS feed and a zip download.
    """

    name = "librivox"
    description = (
        "Search LibriVox (keyless API) for free public-domain audiobooks by "
        "keyword: authors with birth/death years, language, copyright year, "
        "section count, total running time, description and links to the "
        "canonical page, Project Gutenberg source text, RSS feed and zip "
        "download. No API key required."
    )
    tags: ClassVar[list[str]] = ["books", "media", "audio", "knowledge"]

    @staticmethod
    def _snippet(item: dict[str, Any], authors: list[str]) -> str:
        """Compose the snippet for a single audiobook record."""
        parts: list[str] = []

        if authors:
            parts.append("By: " + ", ".join(authors[:_MAX_SNIPPET_AUTHORS]))

        language = _clean(item.get("language"))
        if language:
            parts.append(f"Language: {language}")

        year = _clean(item.get("copyright_year"))
        if year:
            parts.append(f"Year: {year}")

        totaltime = _clean(item.get("totaltime"))
        if totaltime:
            parts.append(f"Duration: {totaltime}")

        sections = _clean(item.get("num_sections"))
        if sections:
            parts.append(f"{sections} sections")

        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a LibriVox audiobook record."""
        title = _clean(item.get("title"))
        if not title:
            return None

        url = _clean(item.get("url_librivox"))
        if not url:
            return None

        authors = _author_names(item.get("authors"))
        description = _strip_html(item.get("description"))[:_MAX_DESCRIPTION_LENGTH]
        totaltimesecs = item.get("totaltimesecs")
        if not isinstance(totaltimesecs, int):
            totaltimesecs = None

        return SearchResult(
            title=title,
            url=url,
            snippet=self._snippet(item, authors),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            extra={
                "id": _clean(item.get("id")) or None,
                "authors": authors,
                "language": _clean(item.get("language")) or None,
                "copyright_year": _clean(item.get("copyright_year")) or None,
                "num_sections": _clean(item.get("num_sections")) or None,
                "totaltime": _clean(item.get("totaltime")) or None,
                "totaltimesecs": totaltimesecs,
                "description": description or None,
                "url_text_source": _clean(item.get("url_text_source")) or None,
                "url_rss": _clean(item.get("url_rss")) or None,
                "url_zip_file": _clean(item.get("url_zip_file")) or None,
                "url_project": _clean(item.get("url_project")) or None,
            },
        )

    def _parse(self, data: object, limit: int) -> ProviderResult:
        """Parse a LibriVox JSON response, preserving the API's order."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        books = data.get("books")
        if not isinstance(books, list):
            return ProviderResult(results=results)

        for item in books:
            if len(results) >= limit:
                break
            if not isinstance(item, dict):
                continue
            built = self._build_result(item, len(results) + 1)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search LibriVox for audiobooks matching *query*.

        A blank query performs no request.  LibriVox's own relevance order is
        preserved.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        request_params: dict[str, Any] = {
            "q": cleaned,
            "format": "json",
            "limit": limit,
        }

        async with self._client() as client:
            resp = await client.get(_ENDPOINT, params=request_params)
            resp.raise_for_status()
            data: object = resp.json()

        return self._parse(data, limit)
