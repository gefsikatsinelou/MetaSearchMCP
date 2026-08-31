"""iNaturalist biodiversity observation search via the keyless public API.

iNaturalist (inaturalist.org) is a global citizen-science platform for
recording observations of wild organisms. Its public REST API requires no
API key or authentication:

``GET https://api.inaturalist.org/v1/observations?q=QUERY&per_page=N``

Each hit carries the species guess, the observation page URL, the observed
date, the taxon (scientific name + iconic group), the observer's username,
and up to two photo thumbnails. The provider is keyless, uses only the
shared httpx client, and tags itself ``biodiversity``/``nature``/``science``
so it can be filtered out of the generic web pool by default.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.inaturalist.org/v1/observations"
# iNaturalist caps a single page at 200 results; keep well below that.
_MAX_API_RESULTS = 50


class INaturalistProvider(BaseProvider):
    """Search wildlife observations on iNaturalist.

    Keyless. Uses the public observations endpoint (``?q=QUERY``) to find
    citizen-science sightings of wild organisms. Each hit carries the
    species guess, the observation page URL, the observed date, taxon
    (scientific name and iconic group), observer username, and photos.
    """

    name = "inaturalist"
    description = (
        "Search citizen-science wildlife observations on iNaturalist — "
        "species, photos, and observer info via the keyless public API."
    )
    tags: ClassVar[list[str]] = ["biodiversity", "nature", "science"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _photo_urls(photos: Any, limit: int = 2) -> list[str]:
        """Return up to *limit* medium-size photo URLs from an observation.

        iNaturalist photo objects carry ``url`` (square) and ``medium_url``
        (medium) variants; the medium variant is preferred when present.
        """
        urls: list[str] = []
        if not isinstance(photos, list):
            return urls
        for photo in photos:
            if not isinstance(photo, dict):
                continue
            url = photo.get("medium_url") or photo.get("url") or ""
            if url:
                urls.append(url)
            if len(urls) >= limit:
                break
        return urls

    def _parse(self, data: Any, limit: int | None = None) -> ProviderResult:
        """Parse the observations response into structured results.

        The response is an object with a ``results`` list; each element
        describes one observation. Non-dict entries and observations without
        a species guess or observation URL are skipped.
        """
        results: list[SearchResult] = []
        max_results = limit or self._max_results
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        observations = data.get("results") or []
        for item in observations:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue

            title = self._clean(item.get("species_guess"))
            if not title:
                continue
            url = item.get("uri") or ""
            if not url:
                continue

            taxon = item.get("taxon") if isinstance(item.get("taxon"), dict) else {}
            scientific_name = self._clean(taxon.get("name"))
            iconic = self._clean(taxon.get("iconic_taxon_name"))
            user = item.get("user") if isinstance(item.get("user"), dict) else {}
            username = self._clean(user.get("login"))
            place = item.get("place") if isinstance(item.get("place"), dict) else {}
            place_name = self._clean(place.get("display_name"))

            snippet_parts: list[str] = []
            if scientific_name and scientific_name != title:
                if iconic:
                    snippet_parts.append(f"{scientific_name} ({iconic})")
                else:
                    snippet_parts.append(scientific_name)
            if place_name:
                snippet_parts.append(place_name)
            if username:
                snippet_parts.append(f"by {username}")

            photos = self._photo_urls(item.get("photos"))
            extra: dict[str, Any] = {
                "scientific_name": scientific_name,
                "iconic_taxon": iconic,
                "observer": username,
                "place": place_name,
            }
            if photos:
                extra["image_url"] = photos[0]
                extra["thumbnail_url"] = photos[0]
                extra["photos"] = photos

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source="inaturalist.org",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=self._iso_date_prefix(item.get("observed_on")),
                    extra=extra,
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search iNaturalist for observations matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(_API_URL, params={"q": query, "per_page": limit})
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit)
