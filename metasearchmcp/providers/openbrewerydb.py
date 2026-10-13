"""Search breweries via the keyless Open Brewery DB API.

Open Brewery DB (openbrewerydb.org) is an open, community-maintained
directory of breweries worldwide. Its v1 API is public and needs no API
key::

    GET https://api.openbrewerydb.org/v1/breweries/search
        ?query=<query>&per_page=10

The ``search`` endpoint matches the keyword against a brewery's name,
city and state/province and returns a plain JSON array (no envelope) of
matching records.  Each record carries the brewery id, name, ``type``
(``micro``, ``brewpub``, ``large``, ``taproom``, ...), full street
address, city, state/province, postal code, country, geographic
coordinates, phone number and website.

The API caps ``per_page`` at 200 entries; this provider keeps requests
well below that and lets the caller paginate.  Because Open Brewery DB is
a data API rather than a website, records have no canonical detail page:
results link to the brewery's own website when known, falling back to the
Open Brewery DB record for that id.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_ENDPOINT = "https://api.openbrewerydb.org/v1/breweries/search"
_SOURCE = "openbrewerydb.org"
# Stable per-record resource used when a brewery has no website of its own.
_RECORD_URL = "https://api.openbrewerydb.org/v1/breweries/{brewery_id}"
# Open Brewery DB caps ``per_page`` at 200 records for a single request.
_MAX_API_RESULTS = 200


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _number(value: object) -> float | None:
    """Return a numeric field, ignoring booleans and non-numeric values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


class OpenBreweryDbProvider(BaseProvider):
    """Search breweries by name, city or region via Open Brewery DB.

    Keyless.  A single request matches *query* against brewery names,
    cities and states/provinces and returns hits in the API's own order,
    each carrying its type, address, coordinates, phone and website.
    """

    name = "openbrewerydb"
    description = (
        "Search breweries worldwide by name, city or region via the keyless "
        "Open Brewery DB API. Each result carries the brewery type, full "
        "address, coordinates, phone and website. No API key required."
    )
    tags: ClassVar[list[str]] = ["food", "drinks", "places"]

    def _location(self, item: dict[str, Any]) -> str:
        """Return a human-readable 'City, State' location for a brewery."""
        city = _clean(item.get("city"))
        region = _clean(item.get("state_province")) or _clean(item.get("state"))
        return ", ".join(part for part in (city, region) if part)

    def _title(self, item: dict[str, Any], brewery_id: str) -> str:
        """Return a brewery's name, falling back to its identifier."""
        return _clean(item.get("name")) or f"Brewery {brewery_id}"

    def _url(self, item: dict[str, Any], brewery_id: str) -> str:
        """Return the brewery's website, or its Open Brewery DB record."""
        return _clean(item.get("website_url")) or _RECORD_URL.format(
            brewery_id=brewery_id
        )

    def _snippet(self, item: dict[str, Any]) -> str:
        """Compose the snippet for a single brewery record.

        The brewery type, location, country (when outside the US) and phone
        number are combined so that a result stays informative even when the
        caller does not look at ``extra``.
        """
        parts: list[str] = []

        brewery_type = _clean(item.get("brewery_type"))
        if brewery_type:
            parts.append(brewery_type)

        location = self._location(item)
        if location:
            parts.append(location)

        country = _clean(item.get("country"))
        if country and country.lower() != "united states":
            parts.append(country)

        phone = _clean(item.get("phone"))
        if phone:
            parts.append(phone)

        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from an Open Brewery DB record."""
        brewery_id = _clean(item.get("id"))
        if not brewery_id:
            return None

        return SearchResult(
            title=self._title(item, brewery_id),
            url=self._url(item, brewery_id),
            snippet=self._snippet(item),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            extra={
                "brewery_id": brewery_id,
                "brewery_type": _clean(item.get("brewery_type")) or None,
                "address": _clean(item.get("address_1")) or None,
                "city": _clean(item.get("city")) or None,
                "state": (
                    _clean(item.get("state_province"))
                    or _clean(item.get("state"))
                    or None
                ),
                "postal_code": _clean(item.get("postal_code")) or None,
                "country": _clean(item.get("country")) or None,
                "phone": _clean(item.get("phone")) or None,
                "website": _clean(item.get("website_url")) or None,
                "latitude": _number(item.get("latitude")),
                "longitude": _number(item.get("longitude")),
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse an Open Brewery DB search response into structured results.

        The API's own order is preserved; any other payload shape yields an
        empty page.
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
        """Search Open Brewery DB for *query*.

        A blank query performs no request.  The keyword is matched against
        brewery names, cities and states/provinces and the API's own
        ranking order is preserved.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        request_params: dict[str, Any] = {
            "query": cleaned,
            "per_page": limit,
        }
        async with self._client() as client:
            resp = await client.get(_ENDPOINT, params=request_params)
            resp.raise_for_status()
            data: object = resp.json()

        return self._parse(data, limit)
