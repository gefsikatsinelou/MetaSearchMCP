"""Project Gutenberg book search via the public, keyless Gutendex API.

Gutendex (gutendex.com) is a community-maintained, keyless JSON API over
the Project Gutenberg catalog of public-domain ebooks. It is the primary
open data source for classic literature:

``GET https://gutendex.com/books/?search=QUERY&page=N``

Each hit carries the title, author(s), language, subject headings, the
project Gutenberg bookshelf, copyright status, download count, and the
canonical Gutenberg ebook page URL. The endpoint is free, requires no
authentication, and is fully searchable via the ``search`` parameter.

The provider is keyless, uses only the shared httpx client, and tags
itself ``academic``/``books`` so it complements Google Books and Open
Library with a focus on public-domain literature.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://gutendex.com/books/"
# Gutendex returns at most 32 books per page.
_MAX_API_RESULTS = 32
# Fallback when a book's formats block lacks a text/html entry.
_BOOK_URL_PREFIX = "https://www.gutenberg.org/ebooks/"


class GutendexProvider(BaseProvider):
    """Search public-domain ebooks in the Project Gutenberg catalog.

    Keyless. Uses the Gutendex JSON API to search the full Project
    Gutenberg catalog. Each hit carries the title, author list,
    language(s), subject headings, Gutenberg bookshelf, download count,
    and the canonical ebook page URL.
    """

    name = "gutendex"
    description = (
        "Search public-domain ebooks (classic literature) in the Project "
        "Gutenberg catalog via Gutendex, no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "books", "knowledge", "web"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _string_list(value: object) -> list[str]:
        """Return a list of cleaned strings from an API list field."""
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        for item in value:
            text = GutendexProvider._clean_text(item)
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned

    @staticmethod
    def _author_list(value: object) -> list[str]:
        """Return author names from the API's author-dict list."""
        if not isinstance(value, list):
            return []
        names: list[str] = []
        for author in value:
            if isinstance(author, dict) and author.get("name"):
                name = GutendexProvider._clean_text(author.get("name"))
                if name and name not in names:
                    names.append(name)
        return names

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the Gutendex JSON response into structured results."""
        results: list[SearchResult] = []
        books = data.get("results") or []
        if not isinstance(books, list):
            return ProviderResult(results=results)

        for i, book in enumerate(books, start=1):
            if not isinstance(book, dict):
                continue
            title = self._clean_text(book.get("title"))
            book_id = book.get("id")
            if not title or not book_id:
                continue

            authors = self._author_list(book.get("authors"))
            languages = self._string_list(book.get("languages"))
            subjects = self._string_list(book.get("subjects"))
            bookshelves = self._string_list(book.get("bookshelves"))
            copyright_status = book.get("copyright")
            downloads = book.get("download_count")

            formats = book.get("formats") or {}
            page_url = ""
            if isinstance(formats, dict):
                page_url = self._clean_text(formats.get("text/html"))
            if not page_url:
                page_url = f"{_BOOK_URL_PREFIX}{book_id}"

            snippet_parts: list[str] = []
            if authors:
                snippet_parts.append(f"By: {', '.join(authors[:5])}")
            if languages:
                snippet_parts.append(f"Language: {', '.join(languages[:3])}")
            if downloads:
                snippet_parts.append(f"Downloads: {downloads:,}")
            if subjects:
                snippet_parts.append(f"Subjects: {', '.join(subjects[:5])}")

            results.append(
                SearchResult(
                    title=title,
                    url=page_url,
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source="gutendex.com",
                    rank=i,
                    provider=self.name,
                    extra={
                        "book_id": str(book_id),
                        "authors": authors,
                        "languages": languages,
                        "subjects": subjects,
                        "bookshelves": bookshelves,
                        "copyright": copyright_status,
                        "download_count": downloads,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Project Gutenberg for ebooks matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {
            "search": query,
            "page": 1,
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        result = self._parse(data)
        # Defensive truncation in case the API returns more than requested.
        result.results = result.results[:limit]
        return result
