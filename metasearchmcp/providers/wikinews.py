"""Wikinews search via the MediaWiki Action API.

Wikinews is a free-content news source written collaboratively by volunteers.
Its MediaWiki Action API requires no authentication and returns clean JSON:

``GET https://en.wikinews.org/w/api.php?action=query&generator=search&...``

The ``generator=search`` + ``prop=extracts`` combination resolves each hit to
its article page and returns the article's lead section as plain text.  The
first line of a Wikinews extract is the article's publication date line
(e.g. ``Sunday, September 13, 2009``), which this provider parses into the
ISO ``published_date`` field.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://en.wikinews.org/w/api.php"

# Wikinews articles traditionally open with a date line; the formats below
# cover the variants seen in practice (with and without the weekday name).
_DATE_FORMATS = ("%A, %B %d, %Y", "%B %d, %Y")


class WikinewsProvider(BaseProvider):
    """Search news articles on Wikinews.

    Keyless. Uses ``generator=search`` with ``prop=extracts`` so each result
    carries the article's lead section as the snippet, along with a direct
    link to the Wikinews article and its parsed publication date.
    """

    name = "wikinews"
    description = (
        "Search collaborative news articles on Wikinews (Wikimedia's "
        "free-content news source), no API key required."
    )
    tags: ClassVar[list[str]] = ["news", "web"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Wikinews for *query* and return matching news articles."""
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
            url = f"https://en.wikinews.org/wiki/{slug}"
            snippet = (page.get("extract") or "").strip()

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source="en.wikinews.org",
                    rank=rank,
                    provider=self.name,
                    published_date=self._extract_published_date(snippet),
                    extra={"pageid": page.get("pageid", 0)},
                ),
            )

        return ProviderResult(results=results)

    @staticmethod
    def _extract_published_date(extract: str) -> str | None:
        """Parse the leading date line of a Wikinews extract into ISO format.

        Wikinews articles start with a date line such as
        ``Sunday, September 13, 2009``. Returns an ISO ``YYYY-MM-DD`` string
        when the first line matches a known format, otherwise ``None``.
        """
        first_line = extract.splitlines()[0].strip() if extract else ""
        if not first_line:
            return None
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(first_line, fmt).date().isoformat()
            except ValueError:
                continue
        return None
