"""Wikibooks search via the MediaWiki Action API.

Wikibooks is the free library of educational textbooks, cookbooks, and
instructional manuals, run by the Wikimedia Foundation.  Its MediaWiki
Action API requires no authentication and returns clean JSON:

``GET https://en.wikibooks.org/w/api.php?action=query&generator=search&...``

The ``generator=search`` + ``prop=extracts`` combination resolves each hit to
its book page (works, chapters, and subpages) and returns the page's lead
section as plain text, which usually summarizes the material matching the
query.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://en.wikibooks.org/w/api.php"


class WikibooksProvider(BaseProvider):
    """Search free textbooks and instructional manuals on Wikibooks.

    Keyless. Uses ``generator=search`` with ``prop=extracts`` so each result
    carries the matching page's lead section as the snippet (truncated to a
    consistent length), along with a direct link to the Wikibooks page.
    """

    name = "wikibooks"
    description = (
        "Search free textbooks, cookbooks, and instructional manuals in "
        "Wikibooks, Wikimedia's open-content textbook collection, "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "knowledge", "books"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Wikibooks for *query* and return matching book pages."""
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
            url = f"https://en.wikibooks.org/wiki/{slug}"
            snippet = (page.get("extract") or "").strip()
            # Wikibooks extracts (e.g. book overviews) can be long;
            # keep snippets consistent with the rest of the catalog.
            snippet = snippet[:MAX_SNIPPET_LENGTH]

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source="en.wikibooks.org",
                    rank=rank,
                    provider=self.name,
                    extra={"pageid": page.get("pageid", 0)},
                ),
            )

        return ProviderResult(results=results)
