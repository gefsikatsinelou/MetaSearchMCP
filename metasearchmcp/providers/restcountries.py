"""Search countries and territories with the keyless REST Countries API.

``restcountries.com`` serves open data about every country and territory —
common and official names, ISO 3166 codes, capital, region and subregion,
population, area, currencies, languages and flag assets — without an API
key::

    GET https://restcountries.com/v3.1/name/QUERY?fields=name,cca2,...

The ``/name`` endpoint performs a partial, case-insensitive match, so
``ger`` finds Germany and ``united`` finds the United States, the United
Kingdom and the United Arab Emirates.  This provider returns one hit per
matching country with its ISO codes, capital, region, population, area,
currencies and languages, plus the country's ``restcountries.com`` record
link.  No API key is required.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_BASE = "https://restcountries.com/v3.1"
_SOURCE = "restcountries.com"
# Trim the response to the fields this provider actually renders.
_FIELDS = (
    "name,cca2,cca3,capital,region,subregion,population,languages,currencies,area,flags"
)
# The name endpoint returns every match in one response; cap what we surface.
_MAX_API_RESULTS = 25


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field, returning ``""`` for empties."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _named_values(value: object) -> list[str]:
    """Render a ``code -> name`` mapping (languages) or ``code -> detail``.

    REST Countries encodes languages as ``{"fra": "French"}`` and
    currencies as ``{"EUR": {"name": "Euro", "symbol": "€"}}``.  This
    helper flattens either shape into a list of human-readable labels,
    appending a symbol in parentheses when one is present.
    """
    if not isinstance(value, dict):
        return []
    labels: list[str] = []
    for item in value.values():
        if isinstance(item, dict):
            name = _clean(item.get("name"))
            symbol = _clean(item.get("symbol"))
            if name and symbol:
                labels.append(f"{name} ({symbol})")
            elif name or symbol:
                labels.append(name or symbol)
        else:
            text = _clean(item)
            if text:
                labels.append(text)
    return labels


class RestCountriesProvider(BaseProvider):
    """Search countries and territories on the keyless REST Countries API."""

    name = "restcountries"
    description = (
        "Search countries and territories via the keyless REST Countries API: "
        "common and official names, ISO 3166 codes, capital, region and "
        "subregion, population, area, currencies and languages with the "
        "country's restcountries.com record link, no API key required."
    )
    tags: ClassVar[list[str]] = ["places", "reference", "geography", "web"]

    @staticmethod
    def _items(payload: object) -> list[dict[str, Any]]:
        """Return the country dicts from a REST Countries response, or ``[]``."""
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    @classmethod
    def _build_result(cls, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a country record, or ``None``."""
        name = item.get("name")
        if isinstance(name, dict):
            title = _clean(name.get("common")) or _clean(name.get("official"))
        else:
            title = _clean(name)
        if not title:
            return None

        cca2 = _clean(item.get("cca2")).upper()
        cca3 = _clean(item.get("cca3")).upper()
        code = cca2 or cca3
        url = f"{_API_BASE}/alpha/{code}" if code else _API_BASE

        parts: list[str] = []

        capitals = item.get("capital")
        if isinstance(capitals, list):
            capital_text = ", ".join(c for c in (_clean(x) for x in capitals) if c)
        else:
            capital_text = _clean(capitals)
        if capital_text:
            parts.append(f"Capital: {capital_text}")

        region = _clean(item.get("region"))
        subregion = _clean(item.get("subregion"))
        location = " / ".join(part for part in (region, subregion) if part)
        if location:
            parts.append(location)

        population = item.get("population")
        if isinstance(population, int) and not isinstance(population, bool):
            parts.append(f"pop. {population:,}")

        area = item.get("area")
        if isinstance(area, (int, float)) and not isinstance(area, bool) and area:
            parts.append(f"{area:,.0f} km²")

        currencies = _named_values(item.get("currencies"))
        if currencies:
            parts.append(", ".join(currencies))

        languages = _named_values(item.get("languages"))
        if languages:
            parts.append("lang: " + ", ".join(languages))

        extra: dict[str, Any] = {"cca2": cca2, "cca3": cca3}
        if region:
            extra["region"] = region
        if subregion:
            extra["subregion"] = subregion
        if isinstance(population, int) and not isinstance(population, bool):
            extra["population"] = population
        flags = item.get("flags")
        if isinstance(flags, dict):
            flag = _clean(flags.get("png")) or _clean(flags.get("svg"))
            if flag:
                extra["flag"] = flag

        return SearchResult(
            title=title,
            url=url,
            snippet=" | ".join(parts)[:MAX_SNIPPET_LENGTH],
            source=_SOURCE,
            rank=rank,
            provider=cls.name,
            extra=extra,
        )

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search REST Countries for countries matching *query* by name.

        A blank query performs no request.  The API answers ``404`` when
        nothing matches, which this method treats as an empty result set
        rather than an error.  Matches are truncated to the requested count.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        async with self._client() as client:
            resp = await client.get(
                f"{_API_BASE}/name/{quote(cleaned, safe='')}",
                params={"fields": _FIELDS},
            )
            # The API signals "no such country" with 404, not an empty list.
            if resp.status_code == 404:
                return ProviderResult(results=[])
            resp.raise_for_status()
            data = resp.json()

        results: list[SearchResult] = []
        for item in self._items(data):
            if len(results) >= limit:
                break
            built = self._build_result(item, len(results) + 1)
            if built is not None:
                results.append(built)
        return ProviderResult(results=results)
