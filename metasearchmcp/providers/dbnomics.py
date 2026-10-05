"""Search economic datasets and time series on DBnomics.

``db.nomics.world`` aggregates thousands of economic databases into a
single, harmonised catalogue — national statistics offices, the OECD,
Eurostat, the IMF, the BIS, the World Bank and many central banks.  Its
keyless REST API offers a full-text search over dataset names and
descriptions::

    GET https://api.db.nomics.world/v22/search?q=QUERY&limit=N

Each hit is a *dataset* carrying its ``code``, ``name``, ``description``,
the providing ``provider_code``/``provider_name`` and the number of series
it holds (``nb_series``) together with how many of them matched the query
(``nb_matching_series``).  The dataset page lives at
``https://db.nomics.world/<provider_code>/<code>``.  A query that matches
nothing answers HTTP 200 with an empty ``docs`` list.

This complements the finance and open-data providers (Yahoo Finance, ECB
rates, data.gov, the World Bank) with a search over official economic and
statistical datasets.  No API key is required.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.db.nomics.world/v22/search"
_DATASET_BASE = "https://db.nomics.world"
# DBnomics paginates with limit/offset; cap the page we request.
_MAX_API_RESULTS = 50
# Keep dataset descriptions short in the snippet field.
_DESCRIPTION_PREVIEW = 240


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _as_int(value: object) -> int | None:
    """Return *value* as an int when it is a whole number, else ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return None


class DBnomicsProvider(BaseProvider):
    """Search economic datasets and time series on DBnomics.

    Keyless.  Issues one search request and returns the matching datasets,
    each with its code, name, description, providing organisation, series
    counts and a link to the dataset page on db.nomics.world.
    """

    name = "dbnomics"
    description = (
        "Search economic and financial datasets from official statistical "
        "organisations (OECD, Eurostat, IMF, BIS, World Bank, national "
        "statistics offices) on DBnomics by keyword: dataset name, "
        "description, provider and series counts, no API key required."
    )
    tags: ClassVar[list[str]] = ["data", "datasets", "finance", "reference"]

    @staticmethod
    def _dataset_url(provider_code: str, code: str) -> str:
        """Return the DBnomics dataset page URL for a provider and code."""
        if not code:
            return ""
        if provider_code:
            return f"{_DATASET_BASE}/{provider_code}/{code}"
        return f"{_DATASET_BASE}/{code}"

    def _build_result(self, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw DBnomics dataset record."""
        code = _clean(item.get("code"))
        if not code:
            return None
        provider_code = _clean(item.get("provider_code"))
        url = self._dataset_url(provider_code, code)
        if not url:
            return None

        title = _clean(item.get("name")) or code
        provider_name = _clean(item.get("provider_name"))
        description = _clean(item.get("description"))
        nb_series = _as_int(item.get("nb_series"))
        nb_matching_series = _as_int(item.get("nb_matching_series"))

        snippet_parts: list[str] = []
        if provider_name:
            snippet_parts.append(provider_name)
        if nb_series is not None:
            snippet_parts.append(f"{nb_series} series")
        if description:
            snippet_parts.append(description[:_DESCRIPTION_PREVIEW])

        published_date = self._iso_date_prefix(
            item.get("updated_at") if isinstance(item.get("updated_at"), str) else None
        ) or self._iso_date_prefix(
            item.get("indexed_at") if isinstance(item.get("indexed_at"), str) else None
        )

        return SearchResult(
            title=title,
            url=url,
            snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
            source="db.nomics.world",
            rank=rank,
            provider=self.name,
            published_date=published_date,
            extra={
                "code": code,
                "provider_code": provider_code or None,
                "provider_name": provider_name or None,
                "nb_series": nb_series,
                "nb_matching_series": nb_matching_series,
            },
        )

    def _parse(self, payload: object) -> ProviderResult:
        """Parse a DBnomics search response into structured search results."""
        results: list[SearchResult] = []
        if not isinstance(payload, dict):
            return ProviderResult(results=results)
        body = payload.get("results")
        if not isinstance(body, dict):
            return ProviderResult(results=results)
        docs = body.get("docs")
        if not isinstance(docs, list):
            return ProviderResult(results=results)

        for item in docs:
            if not isinstance(item, dict):
                continue
            built = self._build_result(item, len(results) + 1)
            if built is not None:
                results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search DBnomics datasets matching *query*.

        A blank query performs no request.  The first ``num_results``
        matching datasets are returned, ranked in the API's relevance order.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        qp: dict[str, Any] = {"q": cleaned, "limit": limit}

        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        result = self._parse(data)
        result.results = result.results[:limit]
        return result
