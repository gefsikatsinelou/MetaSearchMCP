"""Open Library search via the public search API."""

from __future__ import annotations

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://openlibrary.org/search.json"
_MAX_API_RESULTS = 20
_MAX_DISPLAY_ITEMS = 3


class OpenLibraryProvider(BaseProvider):
    """Open Library search via the public search API."""

    name = "openlibrary"
    description = (
        "Search books and authors via Open Library, part of the Internet Archive."
    )
    tags = ["web", "academic", "knowledge", "books"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Open Library for *query* and return book results."""
        qp = {
            "q": query,
            "limit": min(params.num_results, self._max_results, _MAX_API_RESULTS),
            "fields": "key,title,author_name,first_publish_year,edition_count,language",
        }

        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []

        for i, doc in enumerate(data.get("docs", []), start=1):
            key = doc.get("key", "")
            if not key:
                continue
            title = doc.get("title", key.rsplit("/", 1)[-1])
            authors = doc.get("author_name") or []
            year = doc.get("first_publish_year")
            edition_count = doc.get("edition_count", 0)
            languages = doc.get("language") or []

            snippet_parts = []
            if authors:
                snippet_parts.append(", ".join(authors[:_MAX_DISPLAY_ITEMS]))
            if year:
                snippet_parts.append(f"First published: {year}")
            if edition_count:
                snippet_parts.append(f"Editions: {edition_count}")
            if languages:
                snippet_parts.append(
                    f"Languages: {', '.join(languages[:_MAX_DISPLAY_ITEMS])}",
                )

            results.append(
                SearchResult(
                    title=title,
                    url=f"https://openlibrary.org{key}",
                    snippet=" | ".join(snippet_parts),
                    source="openlibrary.org",
                    rank=i,
                    provider=self.name,
                    published_date=str(year) if year else None,
                    extra={
                        "authors": authors,
                        "edition_count": edition_count,
                        "languages": languages,
                    },
                ),
            )

        return ProviderResult(results=results)
