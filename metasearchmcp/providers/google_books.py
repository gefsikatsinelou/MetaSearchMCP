"""Google Books search via the public, keyless Books API.

The Google Books API v1 exposes a read-only volumes endpoint that works
without an API key (requests are subject to IP-based free quotas):

``GET https://www.googleapis.com/books/v1/volumes?q=QUERY&maxResults=N``

Each hit carries the title, authors, publisher, published date, page
count, categories, a short description/snippet, and a link to the book
on Google Books. Google Books complements the Open Library provider by
indexing commercial and in-print titles as well as scanned public-domain
works.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://www.googleapis.com/books/v1/volumes"
# The Books API caps maxResults at 40 per request.
_MAX_API_RESULTS = 40
# Fallback when volumeInfo.infoLink is missing.
_BOOKS_URL_PREFIX = "https://books.google.com/books?id="


class GoogleBooksProvider(BaseProvider):
    """Search books via the Google Books API.

    Keyless, field-restricted volume search. Each result carries the
    title, author list, publisher, publication date, page count,
    categories/languages, and a link to the Google Books page. Exposes
    the raw API metadata in ``extra`` for consumers that want it.
    """

    name = "google_books"
    description = (
        "Search books via the Google Books API (commercial and "
        "public-domain titles), no API key required."
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
        return [
            GoogleBooksProvider._clean_text(item)
            for item in value
            if GoogleBooksProvider._clean_text(item)
        ]

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the Google Books API response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        items = data.get("items")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        for i, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            info = item.get("volumeInfo")
            if not isinstance(info, dict):
                continue

            title = self._clean_text(info.get("title"))
            book_id = str(item.get("id") or "")
            if not title or not book_id:
                continue

            url = self._clean_text(info.get("infoLink")) or (
                f"{_BOOKS_URL_PREFIX}{book_id}"
            )
            authors = self._string_list(info.get("authors"))
            publisher = self._clean_text(info.get("publisher"))
            published_date = self._clean_text(info.get("publishedDate")) or None
            categories = self._string_list(info.get("categories"))
            language = self._clean_text(info.get("language"))

            search_info = item.get("searchInfo")
            snippet_text = ""
            if isinstance(search_info, dict):
                snippet_text = self._clean_text(search_info.get("textSnippet"))
            description = self._clean_text(info.get("description"))
            if not snippet_text:
                snippet_text = description

            snippet_parts: list[str] = []
            if snippet_text:
                snippet_parts.append(snippet_text[:MAX_SNIPPET_LENGTH])
            if authors:
                snippet_parts.append(f"By: {', '.join(authors[:5])}")
            if publisher:
                snippet_parts.append(f"Publisher: {publisher}")
            if categories:
                snippet_parts.append(f"Category: {', '.join(categories[:3])}")

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(snippet_parts),
                    source="books.google.com",
                    rank=i,
                    provider=self.name,
                    published_date=published_date,
                    extra={
                        "book_id": book_id,
                        "authors": authors,
                        "publisher": publisher,
                        "published_date": published_date,
                        "categories": categories,
                        "page_count": self._clean_text(info.get("pageCount")),
                        "language": language,
                        "description": description,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Google Books for volumes matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {
            "q": query,
            "maxResults": str(limit),
            "country": self.country_code(params.country),
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        result = self._parse(data)
        # Truncate defensively in case the API returns more than requested.
        result.results = result.results[:limit]
        return result
