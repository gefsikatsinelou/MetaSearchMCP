"""DBLP computer-science bibliography search via the public, keyless API.

DBLP (dblp.org, Schloss Dagstuhl - Leibniz-Zentrum fuer Informatik) is one
of the most complete open bibliographies for computer science. Its
read-only JSON API requires no API key:

``GET https://dblp.org/search/publ/api?q=QUERY&format=json&h=N``

Each hit exposes the title, venue, year, publication type, DOI, and a
DBLP record URL. The response is a flat JSON document with hits nested
under ``result.hits.hit``; a ``result.hits.@total`` field reports the
overall match count. The provider is keyless and uses only the shared
httpx client from the base provider.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://dblp.org/search/publ/api"
_MAX_API_RESULTS = 50


class DBLPProvider(BaseProvider):
    """Search the DBLP computer-science bibliography.

    Keyless. Uses the public JSON search API over the full DBLP index
    (journals, conference proceedings, and more). Each hit carries the
    title, venue, year, publication type, DOI, and the canonical DBLP
    record URL.
    """

    name = "dblp"
    description = (
        "Search computer-science publications (journals, conference papers) "
        "in the DBLP bibliography, no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "web"]

    @staticmethod
    def _author_list(info: dict[str, Any]) -> list[str]:
        """Return the author names from a DBLP hit's info block.

        DBLP nests authors under ``info.authors.author``, which may be a
        dict (single author) or a list of dicts; each entry carries the
        name in its ``text`` key. Missing or malformed blocks yield an
        empty list.
        """
        authors_raw = (info.get("authors") or {}).get("author") or []
        if not isinstance(authors_raw, list):
            authors_raw = [authors_raw]
        return [
            str(author.get("text", "")).strip()
            for author in authors_raw
            if isinstance(author, dict) and author.get("text")
        ]

    def _parse(
        self,
        data: dict[str, Any],
        max_results: int | None = None,
    ) -> ProviderResult:
        """Parse the DBLP JSON response into structured results."""
        results: list[SearchResult] = []
        limit = max_results or self._max_results
        hits = ((data.get("result") or {}).get("hits") or {}).get("hit") or []

        for hit in hits:
            if not isinstance(hit, dict):
                continue
            info = hit.get("info") or {}
            if not isinstance(info, dict):
                continue
            title = str(info.get("title") or "").strip()
            if not title:
                continue
            url = str(info.get("url") or "").strip() or (
                f"https://dblp.org/rec/{info.get('key')}" if info.get("key") else ""
            )
            if not url:
                continue

            year = info.get("year")
            year_str = str(year).strip() if year is not None else ""
            venue = str(info.get("venue") or "").strip()
            doi = str(info.get("doi") or "").strip()
            ee = str(info.get("ee") or "").strip()

            snippet_parts: list[str] = []
            if venue:
                snippet_parts.append(f"Venue: {venue}")
            if year_str:
                snippet_parts.append(f"Year: {year_str}")
            pub_type = str(info.get("type") or "").strip()
            if pub_type:
                snippet_parts.append(pub_type)

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(snippet_parts),
                    source="dblp.org",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=year_str or None,
                    extra={
                        "authors": self._author_list(info),
                        "venue": venue,
                        "year": year_str,
                        "type": pub_type,
                        "doi": doi,
                        "ee": ee,
                    },
                ),
            )
            if len(results) >= limit:
                break

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the DBLP bibliography for *query* and return publications."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        request_params = {
            "q": query,
            "format": "json",
            "h": limit,
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=request_params)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, max_results=limit)
