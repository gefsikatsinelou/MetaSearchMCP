from __future__ import annotations

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider

_SEARCH_URL = "https://archive.org/advancedsearch.php"


class InternetArchiveProvider(BaseProvider):
    """Internet Archive full-text search via the Advanced Search API.

    Covers books, texts, audio, video, software, and web archives.
    No authentication required.
    """

    name = "internet_archive"
    tags = ["web", "academic", "knowledge"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        qp = {
            "q": query,
            "fl[]": ["identifier", "title", "description", "mediatype", "date", "creator"],
            "rows": min(params.num_results, self._max_results, 20),
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
            description = (description or "")[:400]

            mediatype = doc.get("mediatype", "")
            creator = doc.get("creator", "")
            if isinstance(creator, list):
                creator = ", ".join(creator[:3])
            date = (doc.get("date") or "")[:10]

            url = f"https://archive.org/details/{identifier}"

            snippet_parts = [description]
            if mediatype:
                snippet_parts.append(f"Type: {mediatype}")
            if creator:
                snippet_parts.append(creator)

            results.append(SearchResult(
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
            ))

        return ProviderResult(results=results)
