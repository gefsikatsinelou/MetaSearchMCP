"""Wikiquote search via the MediaWiki Action API.

Wikiquote is a free online compendium of quotations from notable people,
literary works, films, and proverbs. Its MediaWiki Action API requires no
authentication and returns clean JSON:

``GET https://en.wikiquote.org/w/api.php?action=query&generator=search&...``

The ``generator=search`` + ``prop=extracts`` combination resolves each hit to
its page and returns the page's lead section as plain text, which usually
contains the most relevant quotation for the query.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://en.wikiquote.org/w/api.php"


class WikiquoteProvider(BaseProvider):
    """Search quotations on Wikiquote.

    Keyless. Uses ``generator=search`` with ``prop=extracts`` so each result
    carries the matching page's lead quotation as the snippet, along with a
    direct link to the Wikiquote article.
    """

    name = "wikiquote"
    description = (
        "Search quotations from notable people, literature, films, and "
        "proverbs on Wikiquote, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "knowledge", "quotes"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Wikiquote for *query* and return quotation pages."""
        qp = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrlimit": str(min(params.num_results, self._max_results)),
            "prop": "extracts",
            "exintro": "1",
            "explaintext": "1",
            "exlimit": "max",
            "format": "json",
            "utf8": "1",
        }

        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the API response into structured search results."""
        results: list[SearchResult] = []
        pages = data.get("query", {}).get("pages", {})
        if not isinstance(pages, dict):
            return ProviderResult(results=results)

        # Sort by index to preserve search relevance order (MediaWiki returns
        # pages keyed by pageid with an ``index`` field from generator=search).
        ordered = sorted(
            (p for p in pages.values() if isinstance(p, dict)),
            key=lambda p: p.get("index", 0),
        )

        for rank, page in enumerate(ordered, start=1):
            title = page.get("title", "")
            if not title:
                continue
            slug = title.replace(" ", "_")
            url = f"https://en.wikiquote.org/wiki/{slug}"
            snippet = (page.get("extract") or "").strip()

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source="en.wikiquote.org",
                    rank=rank,
                    provider=self.name,
                    extra={"pageid": page.get("pageid", 0)},
                ),
            )

        return ProviderResult(results=results)
