"""Open Library book search via the public, keyless Open Library Search API.

Open Library (openlibrary.org) is the open catalog of the Internet Archive.
The Search API is free and requires no authentication:

``GET https://openlibrary.org/search.json?q=QUERY&limit=N&fields=...``

The response's ``docs`` array carries one entry per book work: title,
authors, first/latest publish year, subject headings, language codes,
edition count, and an ``ia`` list of Internet Archive identifiers. The
``cover_i`` field (present for many works) can be turned into a cover
image URL via ``https://covers.openlibrary.org/b/id/{cover_i}-M.jpg``,
and an ``ia`` identifier yields the readable edition at
``https://archive.org/details/{id}``.

The provider is keyless, uses only the shared httpx client, and tags
itself ``books``/``knowledge``/``academic`` so it complements Google
Books, Gutendex, and Wikisource for literature and reference searches.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://openlibrary.org/search.json"
# The public API caps a single search request at 100 documents.
_MAX_API_RESULTS = 100
# Max number of authors / languages / subjects shown in the snippet.
_MAX_DISPLAY_ITEMS = 3
_MAX_SUBJECTS = 5
# Cover image size variants supported by covers.openlibrary.org.
_COVER_URL_TMPL = "https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
_READABLE_URL_PREFIX = "https://archive.org/details/"
_OL_URL_PREFIX = "https://openlibrary.org"


class OpenLibraryProvider(BaseProvider):
    """Search books and authors via the Open Library Search API.

    Keyless. Each result carries the work title, canonical Open Library
    page URL, author names, first/latest publish year, subject headings,
    language codes, edition count, a thumbnail cover URL when available,
    and the archive.org identifier of a readable edition when available.
    """

    name = "openlibrary"
    description = (
        "Search books and authors via Open Library, part of the Internet Archive, "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "academic", "knowledge", "books"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if value is None:
            return ""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _first_scalar(value: object) -> object | None:
        """Return the first truthy scalar from a value, list, or None.

        Open Library returns single-valued fields either as scalars or as
        one-element lists depending on the query. This normalizes both to
        the underlying value, and returns ``None`` when nothing usable is
        present.
        """
        if isinstance(value, list):
            for item in value:
                if isinstance(item, int) and item > 0:
                    return item
                if isinstance(item, str) and item.strip():
                    return item
            return None
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.strip():
            return value
        return None

    @staticmethod
    def _string_list(value: object) -> list[str]:
        """Return a deduplicated list of cleaned strings from a list field."""
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        for item in value:
            text = OpenLibraryProvider._clean_text(item)
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned

    @staticmethod
    def _cover_url(cover_id: object) -> str:
        """Return a medium cover thumbnail URL from an Open Library cover id."""
        if not cover_id:
            return ""
        return _COVER_URL_TMPL.format(cover_id=cover_id)

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the Search API response into structured search results."""
        results: list[SearchResult] = []
        docs = data.get("docs") or []
        if not isinstance(docs, list):
            return ProviderResult(results=results)

        for i, doc in enumerate(docs, start=1):
            if not isinstance(doc, dict):
                continue
            title = self._clean_text(doc.get("title"))
            key = doc.get("key", "")
            if not title or not key:
                continue

            authors = self._string_list(doc.get("author_name"))
            subjects = self._string_list(doc.get("subject"))
            languages = self._string_list(doc.get("language"))
            edition_count = doc.get("edition_count") or 0
            year = self._first_scalar(doc.get("first_publish_year"))
            if year is None:
                year = self._first_scalar(doc.get("publish_year"))
            latest_year = self._first_scalar(doc.get("latest_publish_year"))
            cover_id = doc.get("cover_i")
            ia_id = self._first_scalar(doc.get("ia"))

            snippet_parts: list[str] = []
            if authors:
                snippet_parts.append(f"By: {', '.join(authors[:_MAX_DISPLAY_ITEMS])}")
            if year:
                snippet_parts.append(f"First published: {year}")
            if edition_count:
                snippet_parts.append(f"Editions: {edition_count}")
            if languages:
                snippet_parts.append(
                    f"Languages: {', '.join(languages[:_MAX_DISPLAY_ITEMS])}",
                )
            if subjects:
                snippet_parts.append(f"Subjects: {', '.join(subjects[:_MAX_SUBJECTS])}")

            results.append(
                SearchResult(
                    title=title,
                    url=f"{_OL_URL_PREFIX}{key}",
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source="openlibrary.org",
                    rank=i,
                    provider=self.name,
                    published_date=str(year) if year else None,
                    extra={
                        "authors": authors,
                        "subjects": subjects,
                        "languages": languages,
                        "edition_count": edition_count,
                        "first_publish_year": year,
                        "latest_publish_year": latest_year,
                        "cover_url": self._cover_url(cover_id),
                        "archive_id": self._clean_text(ia_id),
                        "readable_url": (
                            f"{_READABLE_URL_PREFIX}{self._clean_text(ia_id)}"
                            if ia_id
                            else ""
                        ),
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Open Library for *query* and return book results."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        qp = {
            "q": query,
            "limit": limit,
            "fields": (
                "key,title,author_name,first_publish_year,latest_publish_year,"
                "publish_year,edition_count,language,subject,cover_i,ia"
            ),
        }

        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)
