"""Research Organization Registry (ROR) organization search via a keyless API.

ROR (ror.org) is a community-maintained registry of unique persistent
identifiers for research organizations worldwide.  Its public REST API is
keyless and returns JSON:

``GET https://api.ror.org/v2/organizations?query=QUERY&page=1``

Each hit carries the organization's ROR id, display name, acronyms and
aliases, website, organization type(s), city and country, and founded year.
The API paginates at 20 records per page and exposes no page-size parameter,
so only the first page is requested.  This complements
:mod:`metasearchmcp.providers.orcid` (which indexes *researchers*) by
answering which universities, institutes and labs match a query.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.ror.org/v2/organizations"
# ROR paginates at 20 records per page; there is no page-size parameter.
_MAX_API_RESULTS = 20
# Maximum number of acronyms/aliases listed in a result snippet.
_MAX_NAMES_IN_SNIPPET = 4


class RorProvider(BaseProvider):
    """Search research organizations (universities, institutes, labs) in ROR.

    Keyless.  Uses the public ROR v2 REST API.  Each result carries the ROR
    id, display name and acronyms, website, organization type, city, country,
    and founding year.
    """

    name = "ror"
    description = (
        "Search the Research Organization Registry (ROR) for universities, "
        "research institutes and labs — names, acronyms, country, type — "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "organization", "registry"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _string_list(value: object) -> list[str]:
        """Return a cleaned list of strings from a JSON list field."""
        if not isinstance(value, list):
            return []
        return [
            cleaned
            for cleaned in (RorProvider._clean_text(item) for item in value)
            if cleaned
        ]

    @staticmethod
    def _names_by_type(item: dict[str, Any], name_type: str) -> list[str]:
        """Return cleaned name values tagged with *name_type*."""
        names = item.get("names")
        if not isinstance(names, list):
            return []
        values: list[str] = []
        for entry in names:
            if not isinstance(entry, dict):
                continue
            types = entry.get("types")
            if not isinstance(types, list) or name_type not in types:
                continue
            value = RorProvider._clean_text(entry.get("value"))
            if value:
                values.append(value)
        return values

    @staticmethod
    def _display_name(item: dict[str, Any]) -> str:
        """Return the ROR display name, falling back to the first name given."""
        names = item.get("names")
        if not isinstance(names, list):
            return ""
        display = RorProvider._names_by_type(item, "ror_display")
        if display:
            return display[0]
        for entry in names:
            if not isinstance(entry, dict):
                continue
            value = RorProvider._clean_text(entry.get("value"))
            if value:
                return value
        return ""

    @staticmethod
    def _website(item: dict[str, Any]) -> str:
        """Return the organization's website URL, or an empty string."""
        links = item.get("links")
        if not isinstance(links, list):
            return ""
        for link in links:
            if not isinstance(link, dict):
                continue
            if link.get("type") != "website":
                continue
            value = RorProvider._clean_text(link.get("value"))
            if value:
                return value
        return ""

    @staticmethod
    def _location(item: dict[str, Any]) -> tuple[str, str, str]:
        """Return ``(city, country, country_code)`` for the first location."""
        locations = item.get("locations")
        if not isinstance(locations, list) or not locations:
            return "", "", ""
        first = locations[0]
        if not isinstance(first, dict):
            return "", "", ""
        details = first.get("geonames_details")
        if not isinstance(details, dict):
            return "", "", ""
        return (
            RorProvider._clean_text(details.get("name")),
            RorProvider._clean_text(details.get("country_name")),
            RorProvider._clean_text(details.get("country_code")).upper(),
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a ROR v2 organizations response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        items = data.get("items")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        total = data.get("number_of_results")
        max_results = limit or self._max_results

        for item in items:
            if not isinstance(item, dict):
                continue
            ror_id = self._clean_text(item.get("id"))
            title = self._display_name(item)
            if not ror_id or not title:
                continue

            types = self._string_list(item.get("types"))
            acronyms = self._names_by_type(item, "acronym")
            aliases = self._names_by_type(item, "alias")
            domains = self._string_list(item.get("domains"))
            city, country, country_code = self._location(item)
            website = self._website(item)
            established = item.get("established")
            status = self._clean_text(item.get("status"))

            snippet_parts: list[str] = []
            if types:
                snippet_parts.append(
                    f"Type: {', '.join(t.capitalize() for t in types)}",
                )
            place = ", ".join(part for part in (city, country) if part)
            if place:
                snippet_parts.append(f"Location: {place}")
            if established:
                snippet_parts.append(f"Established: {established}")
            if acronyms:
                snippet_parts.append(
                    f"Acronym: {', '.join(acronyms[:_MAX_NAMES_IN_SNIPPET])}",
                )
            if aliases:
                snippet_parts.append(
                    f"Also known as: {', '.join(aliases[:_MAX_NAMES_IN_SNIPPET])}",
                )

            results.append(
                SearchResult(
                    title=title,
                    url=website or ror_id,
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source="ror.org",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "ror_id": ror_id,
                        "city": city,
                        "country": country,
                        "country_code": country_code,
                        "types": types,
                        "acronyms": acronyms,
                        "aliases": aliases,
                        "domains": domains,
                        "status": status,
                        "established": established or "",
                        "website": website,
                        "total_results": total,
                    },
                ),
            )
            if len(results) >= max_results:
                break

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the Research Organization Registry for *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {"query": query, "page": "1"}
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
