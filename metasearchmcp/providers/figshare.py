"""Figshare repository search via the keyless public API.

Figshare is a general-purpose open research data repository where
researchers deposit datasets, figures, papers, posters, and software
(over 3 million public items). Its read-only public API requires no
API key:

``GET https://api.figshare.com/v2/articles?search_for=QUERY&page_size=N``

Each hit exposes the item title, DOI, defined type (dataset, figure,
paper, poster, media, file set, ...), published date, and a canonical
landing-page link. Figshare complements Zenodo and OSF Preprints by
indexing research data and scholarly output that those repositories
do not hold.
"""

from __future__ import annotations

from typing import ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.figshare.com/v2/articles"
_MAX_API_RESULTS = 50


class FigshareProvider(BaseProvider):
    """Search research data and scholarly output deposited on Figshare.

    Keyless. Uses the public articles API, which covers datasets,
    figures, papers, posters, and other deposit types. Each hit
    carries the title, DOI, defined type, published date, and a
    canonical landing-page link.
    """

    name = "figshare"
    description = (
        "Search open research data and scholarly output deposited on "
        "Figshare (datasets, figures, papers, posters), no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "web", "datasets", "repositories"]

    @staticmethod
    def _strip_control(value: object) -> str:
        """Collapse whitespace/control characters in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    def _parse(
        self,
        data: object,
        max_results: int | None = None,
    ) -> ProviderResult:
        """Parse the Figshare articles response into structured results."""
        results: list[SearchResult] = []
        limit = max_results or self._max_results
        if not isinstance(data, list):
            return ProviderResult(results=results)

        for i, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                continue
            title = self._strip_control(item.get("title"))
            if not title:
                continue

            url = item.get("url_public_html") or item.get("url") or ""
            item_type = item.get("defined_type_name") or ""
            description = self._strip_control(item.get("description"))
            snippet = description[:MAX_SNIPPET_LENGTH]

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source="figshare.com",
                    rank=i,
                    provider=self.name,
                    published_date=self._iso_date_prefix(item.get("published_date")),
                    extra={
                        "doi": item.get("doi") or "",
                        "item_type": item_type,
                        "published_date_full": item.get("published_date") or "",
                    },
                ),
            )
            if i >= limit:
                break

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Figshare for *query* and return deposited research items."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        qp = {
            "search_for": query,
            "page_size": str(limit),
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, max_results=limit)
