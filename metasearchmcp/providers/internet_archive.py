"""Internet Archive full-text search via the Advanced Search API."""

from __future__ import annotations

from typing import ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://archive.org/advancedsearch.php"
_MAX_API_RESULTS = 20
_MAX_CREATORS_SHOWN = 3


class InternetArchiveProvider(BaseProvider):
    """Internet Archive full-text search via the Advanced Search API.

    Covers books, texts, audio, video, software, and web archives.
    No authentication required.
    """

    name = "internet_archive"
    description = (
        "Search Internet Archive collections, including texts, media, and software."
    )
    tags: ClassVar[list[str]] = ["web", "academic", "knowledge"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Internet Archive for *query* and return archived items."""
        qp = {
            "q": query,
            "fl[]": [
                "identifier",
                "title",
                "description",
                "mediatype",
                "date",
                "creator",
            ],
            "rows": min(params.num_results, self._max_results, _MAX_API_RESULTS),
            "page": 1,
            "output": "json",
        }

        async with self._client() as client:
            resp = await client.get(_SEARCH_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []
        docs = data.get("response", {}).get("docs", [])

        for i, doc in enumerate(docs, start=1):
            identifier = doc.get("identifier", "")
            title = doc.get("title", identifier)
            if isinstance(title, list):
                title = title[0] if title else ""

            description = doc.get("description", "")
            if isinstance(description, list):
                description = " ".join(description)
            description = (description or "")[:MAX_SNIPPET_LENGTH]

            mediatype = doc.get("mediatype", "")
            creator = doc.get("creator", "")
            if isinstance(creator, list):
                creator = ", ".join(creator[:_MAX_CREATORS_SHOWN])
            date = (doc.get("date") or "")[:10]

            url = f"https://archive.org/details/{identifier}"

            snippet_parts = [description]
            if mediatype:
                snippet_parts.append(f"Type: {mediatype}")
            if creator:
                snippet_parts.append(creator)

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(p for p in snippet_parts if p),
                    source="archive.org",
                    rank=i,
                    provider=self.name,
                    published_date=date or None,
                    extra={
                        "identifier": identifier,
                        "mediatype": mediatype,
                        "creator": creator,
                    },
                ),
            )

        return ProviderResult(results=results)
