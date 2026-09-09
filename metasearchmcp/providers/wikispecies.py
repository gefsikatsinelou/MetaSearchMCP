"""Wikispecies search via the MediaWiki Action API.

Wikispecies is Wikimedia's open taxonomic directory: it catalogs the
scientific names, classification, and vernacular names of living and
extinct organisms, from kingdoms down to subspecies.  Its MediaWiki
Action API requires no authentication and returns clean JSON:

``GET https://species.wikimedia.org/w/api.php?action=query&generator=search&...``

The ``generator=search`` + ``prop=extracts`` combination resolves each hit to
its taxon page and returns the page's plain-text content.  For Wikispecies
pages the extract is dominated by the ``Taxonavigation`` section — the full
parent classification (family, subfamily, genus, species, ...) — and the
``Name`` section, which records the taxon author and type locality.  That
structured classification is exactly what a taxonomy search should surface.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://species.wikimedia.org/w/api.php"
# Wikispecies classification extracts can be long (whole genus/subspecies
# listings); bound what we download, then trim locally to a consistent size.
_EXTRACT_CHARS = MAX_SNIPPET_LENGTH * 3


class WikispeciesProvider(BaseProvider):
    """Search species pages and taxonomic classification on Wikispecies.

    Keyless. Uses ``generator=search`` with ``prop=extracts`` so each result
    carries the matching taxon's classification and name section as the
    snippet (truncated to a consistent length), along with a direct link to
    the Wikispecies taxon page.
    """

    name = "wikispecies"
    description = (
        "Search species and higher taxa — scientific names, classification, "
        "and taxon authors in Wikispecies, Wikimedia's open species "
        "directory, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "knowledge", "nature", "biodiversity"]

    @staticmethod
    def _clean_snippet(extract: str) -> str:
        """Turn a raw Wikispecies extract into a compact taxonomy snippet.

        Skips ``== Section ==`` headings and blank lines, collapses each
        remaining classification line onto a single line, and joins them
        into one truncated snippet (e.g. ``Familia: Felidae | Genus: ...``).
        """
        if not extract:
            return ""
        parts: list[str] = []
        for line in extract.splitlines():
            stripped = " ".join(line.split())
            if not stripped or stripped.startswith("="):
                continue
            parts.append(stripped)
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Wikispecies for *query* and return matching taxon pages."""
        qp = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrlimit": str(min(params.num_results, self._max_results)),
            "prop": "extracts",
            "explaintext": "1",
            "exchars": str(_EXTRACT_CHARS),
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
            url = f"https://species.wikimedia.org/wiki/{slug}"
            snippet = self._clean_snippet(page.get("extract") or "")

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source="species.wikimedia.org",
                    rank=rank,
                    provider=self.name,
                    extra={"pageid": page.get("pageid", 0)},
                ),
            )

        return ProviderResult(results=results)
