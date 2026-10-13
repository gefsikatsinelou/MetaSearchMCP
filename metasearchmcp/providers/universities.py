"""Search universities and colleges with the keyless Hipolabs directory API.

The Hipolabs Universities API (universities.hipolabs.com) is an open,
community-maintained directory of higher-education institutions worldwide.
It needs no API key and exposes a single substring search over institution
names::

    GET http://universities.hipolabs.com/search?name=QUERY[&country=NAME]

``name`` matches any part of an institution's name (case-insensitive), so
``stanford`` finds Stanford University and ``institute of technology`` finds
every institute of technology in the directory.  Each record carries the
institution name, its ISO 3166 alpha-2 country code and country name, an
optional state/province, one or more web pages and one or more e-mail-style
domains.

The API answers with a plain JSON array (no envelope) and returns ``[]``
when nothing matches.  Records have no canonical detail page, so results
link to the institution's own website when known, falling back to its first
domain.  The endpoint is served over plain HTTP only.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_ENDPOINT = "http://universities.hipolabs.com/search"
_SOURCE = "universities.hipolabs.com"
# The API returns every match in one response; cap what we surface.
_MAX_API_RESULTS = 50


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _string_list(value: object) -> list[str]:
    """Return the non-empty cleaned strings from a list field, or ``[]``."""
    if not isinstance(value, list):
        return []
    cleaned = (_clean(item) for item in value)
    return [item for item in cleaned if item]


class UniversitiesProvider(BaseProvider):
    """Search higher-education institutions by name via the Hipolabs API.

    Keyless.  A single request performs a substring match against
    institution names and returns matching universities and colleges with
    their country, state/province, website and domain.
    """

    name = "universities"
    description = (
        "Search universities and colleges worldwide by name via the keyless "
        "Hipolabs Universities directory. Each result carries the country, "
        "state/province, website and domain. No API key required."
    )
    tags: ClassVar[list[str]] = ["education", "reference", "places"]

    @staticmethod
    def _url(item: dict[str, Any], name: str) -> str:
        """Return the institution's website, or its first domain, or a fallback.

        Prefers the first ``web_pages`` entry, then falls back to the first
        e-mail-style ``domains`` value (prefixed with ``https://`` and with a
        leading ``www.`` stripped), and finally to the search URL itself.
        """
        web_pages = _string_list(item.get("web_pages"))
        if web_pages:
            return web_pages[0]

        domains = _string_list(item.get("domains"))
        if domains:
            domain = domains[0]
            if domain.startswith(("http://", "https://")):
                return domain
            return f"https://{domain.removeprefix('www.')}"

        return f"{_ENDPOINT}?name={quote(name, safe='')}"

    @staticmethod
    def _snippet(item: dict[str, Any]) -> str:
        """Compose the snippet for a single institution record.

        The country, optional state/province and domains are combined so a
        result stays informative even when ``extra`` is not inspected.
        """
        parts: list[str] = []

        country = _clean(item.get("country"))
        if country:
            parts.append(country)

        state = _clean(item.get("state-province")) or _clean(item.get("state_province"))
        if state:
            parts.append(state)

        domains = _string_list(item.get("domains"))
        if domains:
            parts.append(", ".join(domains))

        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(self, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a directory record, or ``None``."""
        name = _clean(item.get("name"))
        if not name:
            return None

        domains = _string_list(item.get("domains"))
        web_pages = _string_list(item.get("web_pages"))

        return SearchResult(
            title=name,
            url=self._url(item, name),
            snippet=self._snippet(item),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            extra={
                "country": _clean(item.get("country")) or None,
                "alpha_two_code": _clean(item.get("alpha_two_code")) or None,
                "state_province": (
                    _clean(item.get("state-province"))
                    or _clean(item.get("state_province"))
                    or None
                ),
                "domains": domains or None,
                "web_pages": web_pages or None,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a Hipolabs search response into structured results.

        The API's own order is preserved; records without a name are skipped
        and any other payload shape yields an empty page.
        """
        results: list[SearchResult] = []
        if not isinstance(data, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in data:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            built = self._build_result(item, len(results) + 1)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the Hipolabs directory for institutions matching *query*.

        A blank query performs no request.  The keyword is matched as a
        case-insensitive substring against institution names and the API's
        own order is preserved.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(_ENDPOINT, params={"name": cleaned})
            resp.raise_for_status()
            data: object = resp.json()

        return self._parse(data, limit)
