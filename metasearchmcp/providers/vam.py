"""Search the Victoria and Albert Museum (V&A) collection via its keyless API.

The V&A in London publishes a public, keyless v2 API in front of its collection
catalogue — one of the largest collections of decorative arts, design, fashion
and sculpture in the world::

    GET https://api.vam.ac.uk/v2/objects/search?q=QUERY&page_size=N&page=1

The response is ``{"info": {...}, "records": [...], "clusters": {...}}`` where
``info`` reports the total match count (``record_count``), the page size, the
page number and how many of the matches carry images, and ``records`` holds one
compact object per match.  Records are returned without a follow-up request, so
each hit carries the object's system number, accession number and object type,
its primary title, maker (with the association such as ``designer`` or
``manufacturer``), production date and place, the location it is currently held
in (including whether it is on display) and the IIIF image base URL of its
primary photograph.

This complements the museum providers already present (Met Museum, Art
Institute of Chicago, Cleveland Museum of Art) with a major European
design/decorative-arts collection.  No API key is required.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://api.vam.ac.uk/v2/objects/search"
# Human-readable object page; the trailing slash keeps the canonical form.
_ITEM_URL = "https://collections.vam.ac.uk/item/"
# The search API caps ``page_size`` at 100 records per request.
_MAX_API_RESULTS = 100


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _int(value: object) -> int | None:
    """Return an integer field, ignoring booleans and non-integer values."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _maker(item: object) -> tuple[str, str]:
    """Return the primary maker's name and its association with the object."""
    if not isinstance(item, dict):
        return "", ""
    maker = item.get("_primaryMaker")
    if not isinstance(maker, dict):
        return "", ""
    return _clean(maker.get("name")), _clean(maker.get("association"))


def _images(item: object) -> dict[str, Any]:
    """Return a record's image block, or an empty mapping when absent."""
    if not isinstance(item, dict):
        return {}
    images = item.get("_images")
    return images if isinstance(images, dict) else {}


def _location(item: object) -> tuple[str, str, bool]:
    """Return a record's current location, its site code and display status."""
    if not isinstance(item, dict):
        return "", "", False
    location = item.get("_currentLocation")
    if not isinstance(location, dict):
        return "", "", False
    return (
        _clean(location.get("displayName")),
        _clean(location.get("site")),
        bool(location.get("onDisplay")),
    )


def _warnings(item: object) -> list[str]:
    """Return a record's warning labels, e.g. handling restrictions."""
    if not isinstance(item, dict):
        return []
    raw = item.get("_warningTypes")
    if not isinstance(raw, list):
        return []
    return [label for label in (_clean(entry) for entry in raw) if label]


def _total_results(data: object) -> int | None:
    """Return the total number of matching objects from the ``info`` block."""
    if not isinstance(data, dict):
        return None
    info = data.get("info")
    if not isinstance(info, dict):
        return None
    return _int(info.get("record_count"))


class VamProvider(BaseProvider):
    """Search objects in the Victoria and Albert Museum collection.

    Keyless.  *query* is matched against the collection catalogue and each hit
    links to its object page on collections.vam.ac.uk, carrying the object type,
    maker, date and place of production, current location and image URLs.
    """

    name = "vam"
    description = (
        "Search the Victoria and Albert Museum (V&A) collection — decorative "
        "arts, design, fashion and sculpture: object type, title, maker, "
        "production date and place, current location and IIIF image URLs via "
        "the keyless V&A API. No API key required."
    )
    tags: ClassVar[list[str]] = ["art", "images", "media"]

    @staticmethod
    def _title(item: dict[str, Any]) -> str:
        """Return the record's display title, falling back to object type.

        Most V&A records have no primary title beyond their object type (e.g.
        ``Chair``) or their accession number, so both are used as fallbacks.
        """
        for field in ("_primaryTitle", "objectType", "accessionNumber"):
            title = _clean(item.get(field))
            if title:
                return title
        return ""

    @staticmethod
    def _snippet(
        object_type: str,
        maker: str,
        association: str,
        date: str,
        place: str,
        location: str,
        on_display: bool,
        image_url: str,
    ) -> str:
        """Compose the snippet for a single collection object."""
        parts: list[str] = []
        if object_type:
            parts.append(object_type)
        if maker:
            label = f"by {maker} ({association})" if association else f"by {maker}"
            parts.append(label)
        if date:
            parts.append(date)
        if place:
            parts.append(place)
        if location:
            prefix = "On display" if on_display else "Location"
            parts.append(f"{prefix}: {location}")
        if image_url:
            parts.append("image available")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        total: int | None,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a V&A collection record."""
        system_number = _clean(item.get("systemNumber"))
        title = self._title(item)
        if not system_number or not title:
            return None

        images = _images(item)
        thumbnail = _clean(images.get("_primary_thumbnail"))
        image_url = _clean(images.get("_iiif_image_base_url"))
        maker, association = _maker(item)
        location, site, on_display = _location(item)
        date = _clean(item.get("_primaryDate"))
        place = _clean(item.get("_primaryPlace"))
        object_type = _clean(item.get("objectType"))
        accession_number = _clean(item.get("accessionNumber"))
        url = f"{_ITEM_URL}{quote(system_number)}/"

        return SearchResult(
            title=title,
            url=url,
            snippet=self._snippet(
                object_type,
                maker,
                association,
                date,
                place,
                location,
                on_display,
                image_url or thumbnail,
            ),
            source="collections.vam.ac.uk",
            rank=rank,
            provider=self.name,
            extra={
                "system_number": system_number,
                "accession_number": accession_number or None,
                "object_type": object_type or None,
                "maker": maker or None,
                "maker_association": association or None,
                "date": date or None,
                "place": place or None,
                "on_display": on_display,
                "location": location or None,
                "site": site or None,
                "image_id": _clean(images.get("_primaryImageId"))
                or _clean(item.get("_primaryImageId"))
                or None,
                "thumbnail_url": thumbnail or None,
                "image_url": image_url or None,
                "image_resolution": _clean(images.get("imageResolution")) or None,
                "available_to_book": bool(item.get("availableToBook")),
                "warnings": _warnings(item),
                "item_url": url,
                "total_results": total,
            },
        )

    def _parse(
        self,
        data: object,
        limit: int | None = None,
    ) -> ProviderResult:
        """Parse a V&A search response into structured results.

        The API's own relevance order is preserved; any other payload shape
        yields an empty result set.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        items = data.get("records")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        total = _total_results(data)
        max_results = self._max_results if limit is None else limit
        for item in items:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            built = self._build_result(item, total, len(results) + 1)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the V&A collection for objects matching *query*.

        A blank query performs no request.  A single page is fetched, sized to
        ``num_results`` and capped at the API's ``page_size`` maximum.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        if limit <= 0:
            return ProviderResult(results=[])

        async with self._client() as client:
            resp = await client.get(
                _SEARCH_URL,
                params={"q": cleaned, "page_size": limit, "page": 1},
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit)
