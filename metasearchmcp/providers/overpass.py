"""OpenStreetMap feature search via the public Overpass API.

Overpass is the query engine over the OpenStreetMap planet database. Where a
geocoder such as Nominatim returns one best match for a place name, Overpass
returns *every* mapped feature whose name matches a pattern -- cafés, shops,
hospitals, museums, railway stations, national parks, named streets and
everything else carrying a ``name`` tag -- together with the feature's tags,
its coordinates and a link to its page on openstreetmap.org.

The public instance is keyless and takes the whole query in the ``data``
parameter::

    GET https://overpass-api.de/api/interpreter?data=<OverpassQL>

A free-text query becomes a case-insensitive name match over nodes, ways and
relations::

    [out:json][timeout:8];
    area["ISO3166-1"="US"][admin_level=2]->.searchArea;
    nwr(area.searchArea)["name"~"coffee.*shop",i];
    out center 20;

Scoping the search to the country in the search options keeps the query
tractable on the shared public instance (a planet-wide name scan is much
slower). A country that is not a two-letter code -- ``global``, for instance
-- drops the area clause and searches the whole planet.

Queries the public instance cannot finish inside its own timeout come back
with an empty ``elements`` list and a ``remark`` instead of an error status;
those are reported here as an empty result set, as are malformed queries,
which the instance answers with HTTP 400 (raised as a provider error).
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://overpass-api.de/api/interpreter"
_SOURCE = "openstreetmap.org"
# Seconds the public instance may spend on one query. Kept well below the
# provider HTTP timeout so a slow query is cut short server-side and answers
# with a parseable body instead of hanging the client.
_QUERY_TIMEOUT_SECONDS = 8
# Features requested per query.
_MAX_API_RESULTS = 50
# Longest snippet an address is allowed to occupy.
_SNIPPET_ADDRESS_LENGTH = 120
# Tag keys that classify a feature, in priority order: the first one present
# names the feature's category (``amenity=cafe``, ``shop=bakery``, ...).
_CATEGORY_KEYS = (
    "amenity",
    "shop",
    "tourism",
    "leisure",
    "office",
    "craft",
    "historic",
    "natural",
    "highway",
    "railway",
    "aeroway",
    "man_made",
    "place",
    "landuse",
)
# Characters escaped before the query is embedded in an Overpass regex, plus
# the quote and backslash that would otherwise break the Overpass QL string.
_REGEX_SPECIALS = frozenset('.^$*+?()[]{}|\\"')
# Overpass element types whose ids form an openstreetmap.org page URL.
_ELEMENT_TYPES = frozenset({"node", "way", "relation"})


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _number(value: object) -> float | None:
    """Return *value* as a float, ignoring booleans and non-numeric values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _escape_regex(text: str) -> str:
    """Escape regex metacharacters so *text* matches literally."""
    return "".join("\\" + char if char in _REGEX_SPECIALS else char for char in text)


def _pattern(query: str) -> str:
    """Turn a free-text query into an Overpass name regex.

    Every whitespace-separated token is escaped and the tokens are joined with
    ``.*``, so ``coffee shop`` matches ``Coffee Shop``, ``CoffeeShop`` and
    ``Coffeeshop & Roastery`` alike.
    """
    return ".*".join(_escape_regex(token) for token in query.split())


def _truncate(value: str, limit: int) -> str:
    """Shorten *value* to *limit* characters, appending an ellipsis."""
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _build_query(pattern: str, country: str, limit: int) -> str:
    """Build the Overpass QL for a name search over every element type.

    When *country* is a two-letter code the search is restricted to that
    country with an area filter; otherwise the whole planet is searched.
    """
    settings = f"[out:json][timeout:{_QUERY_TIMEOUT_SECONDS}];"
    if country:
        scope = (
            f'area["ISO3166-1"="{country}"][admin_level=2]->.searchArea;'
            f'nwr(area.searchArea)["name"~"{pattern}",i];'
        )
    else:
        scope = f'nwr["name"~"{pattern}",i];'
    return f"{settings}\n{scope}\nout center {limit};"


def _address(tags: dict[str, Any]) -> tuple[str, str, str]:
    """Return ``(address, city, postcode)`` from a feature's ``addr:*`` tags."""
    street = _clean(tags.get("addr:street"))
    number = _clean(tags.get("addr:housenumber"))
    city = _clean(tags.get("addr:city"))
    postcode = _clean(tags.get("addr:postcode"))

    line = " ".join(part for part in (street, number) if part)
    locality = " ".join(part for part in (postcode, city) if part)
    address = ", ".join(part for part in (line, locality) if part)
    return address, city, postcode


def _category(tags: dict[str, Any]) -> tuple[str, str]:
    """Return the ``(key, value)`` tag pair that classifies a feature."""
    for key in _CATEGORY_KEYS:
        value = _clean(tags.get(key))
        if value:
            return key, value
    return "", ""


class OverpassProvider(BaseProvider):
    """Search OpenStreetMap features by name through the Overpass API.

    Keyless. *query* becomes a case-insensitive name match over nodes, ways
    and relations, scoped to the country named in the search options (pass a
    non-country value such as ``global`` to search the planet). Each result
    carries the feature's name, its category, address, opening hours and
    contact details when tagged, its coordinates, and a link to the
    openstreetmap.org feature page.
    """

    name = "overpass"
    description = (
        "Search OpenStreetMap features by name via the keyless Overpass API "
        "(shops, amenities, museums, stations, parks and other named map "
        "features, with category, address, opening hours, coordinates and a "
        "link to the OSM feature page), scoped to the requested country."
    )
    tags: ClassVar[list[str]] = ["places", "geo", "web", "maps"]

    def _area_country(self, country: str) -> str:
        """Return the two-letter country code scoping the query.

        Values that are not a two-letter country code (``global``, say) yield
        an empty string, which searches the whole planet instead.
        """
        code = self.country_code(country)
        return code if len(code) == 2 and code.isalpha() else ""

    @staticmethod
    def _element_key(element: dict[str, Any]) -> tuple[str, str] | None:
        """Return the ``(type, id)`` identity of an Overpass element.

        ``None`` is returned for elements missing a usable type or id, which
        cannot be linked to an openstreetmap.org page.
        """
        element_type = _clean(element.get("type"))
        element_id = element.get("id")
        if element_type not in _ELEMENT_TYPES or isinstance(element_id, bool):
            return None
        if not isinstance(element_id, (int, str)) or not str(element_id):
            return None
        return element_type, str(element_id)

    @staticmethod
    def _coordinates(element: dict[str, Any]) -> tuple[float | None, float | None]:
        """Return a feature's coordinates.

        Nodes carry ``lat``/``lon`` directly; ways and relations are queried
        with ``out center`` and carry them in a ``center`` object instead.
        """
        lat = _number(element.get("lat"))
        lon = _number(element.get("lon"))
        if lat is not None and lon is not None:
            return lat, lon

        center = element.get("center")
        if not isinstance(center, dict):
            return lat, lon
        return _number(center.get("lat")), _number(center.get("lon"))

    def _build_result(
        self,
        element: dict[str, Any],
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw Overpass element."""
        tags = element.get("tags")
        if not isinstance(tags, dict):
            return None
        name = _clean(tags.get("name"))
        if not name:
            return None
        key = self._element_key(element)
        if key is None:
            return None
        element_type, element_id = key

        category_key, category_value = _category(tags)
        address, city, postcode = _address(tags)
        hours = _clean(tags.get("opening_hours"))
        brand = _clean(tags.get("brand"))
        operator = _clean(tags.get("operator"))
        phone = _clean(tags.get("phone")) or _clean(tags.get("contact:phone"))
        website = _clean(tags.get("website")) or _clean(tags.get("contact:website"))
        lat, lon = self._coordinates(element)

        parts: list[str] = []
        if category_key:
            parts.append(f"{category_key}={category_value}")
        if address:
            parts.append(_truncate(address, _SNIPPET_ADDRESS_LENGTH))
        if hours:
            parts.append(f"Hours: {hours}")
        if brand or operator:
            parts.append(brand or operator)
        if phone:
            parts.append(phone)
        if website:
            parts.append(website)
        if lat is not None and lon is not None:
            parts.append(f"Coordinates: {lat:.5f}, {lon:.5f}")

        return SearchResult(
            title=name,
            url=f"https://www.openstreetmap.org/{element_type}/{element_id}",
            snippet=" | ".join(parts)[:MAX_SNIPPET_LENGTH],
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            extra={
                "osm_type": element_type,
                "osm_id": element_id,
                "category": category_key or None,
                "category_value": category_value or None,
                "address": address or None,
                "city": city or None,
                "postcode": postcode or None,
                "opening_hours": hours or None,
                "phone": phone or None,
                "website": website or None,
                "brand": brand or None,
                "operator": operator or None,
                "wikipedia": _clean(tags.get("wikipedia")) or None,
                "wikidata": _clean(tags.get("wikidata")) or None,
                "lat": lat,
                "lon": lon,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse an Overpass response into structured results.

        Elements are deduplicated by type/id and returned in the instance's
        ``out center`` order. A timeout or malformed-query body without usable
        elements yields an empty result set.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        elements = data.get("elements")
        if not isinstance(elements, list):
            return ProviderResult(results=results)

        max_results = self._max_results if limit is None else limit
        seen: set[tuple[str, str]] = set()
        for element in elements:
            if len(results) >= max_results:
                break
            if not isinstance(element, dict):
                continue
            key = self._element_key(element)
            if key is None or key in seen:
                continue
            built = self._build_result(element, len(results) + 1)
            if built is None:
                continue
            seen.add(key)
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search OpenStreetMap for features whose name matches *query*.

        A blank query performs no request. The query is scoped to the country
        in *params*; a value that is not a two-letter country code searches the
        whole planet.
        """
        cleaned = " ".join(query.split())
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        if limit <= 0:
            return ProviderResult(results=[])

        body = _build_query(
            _pattern(cleaned),
            self._area_country(params.country),
            limit,
        )
        async with self._client() as client:
            resp = await client.get(_API_URL, params={"data": body})
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
