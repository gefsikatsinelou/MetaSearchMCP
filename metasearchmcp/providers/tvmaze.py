"""TVMaze TV show search via the keyless public REST API.

TVMaze exposes an unauthenticated search endpoint that returns matching TV
shows with rich structured metadata:

``GET https://api.tvmaze.com/search/shows?q=QUERY``

Each hit is a ``{"score": ..., "show": {...}}`` object where the nested
``show`` document carries the title, landing page, genres, status, runtime,
premiere date, network, and an HTML summary. No API key or authentication is
required; parsing uses BeautifulSoup (already a project dependency) to strip
the summary HTML, plus the shared httpx client from the base provider.

Note: the API is community-run and may be rate-limited; results are
best-effort.
"""

from __future__ import annotations

from typing import Any, ClassVar

from bs4 import BeautifulSoup

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://api.tvmaze.com/search/shows"
# TVMaze returns at most this many shows per request.
_MAX_API_RESULTS = 10


class TVMazeProvider(BaseProvider):
    """Search TV shows and series via TVMaze.

    Uses the keyless public search API, which requires no authentication and
    returns rich structured metadata per show: title, landing page, genres,
    status, premiere date, network, and a short HTML summary.
    """

    name = "tvmaze"
    description = (
        "Search TV shows and series worldwide — titles, genres, status, "
        "network, and premiere dates via the keyless TVMaze API."
    )
    tags: ClassVar[list[str]] = ["video", "media", "tv"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search TVMaze for shows matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(_API_URL, params={"q": query})
            resp.raise_for_status()
            data = resp.json()

        result = self._parse(data)
        # Truncate to the requested limit (the API returns up to 10 shows).
        result.results = result.results[:limit]
        return result

    @staticmethod
    def _show_title(show: dict[str, Any]) -> str:
        """Return the show name, falling back to its TVMaze page URL."""
        return str(show.get("name") or "").strip() or str(show.get("url") or "")

    @staticmethod
    def _show_network(show: dict[str, Any]) -> str:
        """Return the primary broadcaster or streaming channel name."""
        network = show.get("network") or {}
        web = show.get("webChannel") or {}
        return str(network.get("name") or web.get("name") or "")

    @staticmethod
    def _show_country(show: dict[str, Any]) -> str:
        """Return the show's production country, if known."""
        network = show.get("network") or {}
        country = network.get("country") or {}
        return str(country.get("name") or "")

    @staticmethod
    def _clean_summary(summary: object) -> str:
        """Strip HTML tags from the show summary and collapse whitespace."""
        html = str(summary or "")
        if not html.strip():
            return ""
        soup = BeautifulSoup(html, "lxml")
        return " ".join(soup.get_text(" ", strip=True).split())

    def _parse(self, data: Any) -> ProviderResult:
        """Parse the TVMaze search response into structured search results."""
        results: list[SearchResult] = []
        if not isinstance(data, list):
            return ProviderResult(results=results)

        for i, item in enumerate(data, start=1):
            show = item.get("show") if isinstance(item, dict) else None
            if not isinstance(show, dict):
                continue

            url = str(show.get("url") or "")
            title = self._show_title(show)
            if not url or not title:
                continue

            genres = [str(g) for g in (show.get("genres") or []) if g]
            network = self._show_network(show)
            summary = self._clean_summary(show.get("summary"))
            premiered = self._iso_date_prefix(show.get("premiered"))
            image = show.get("image") or {}
            thumb = str(image.get("medium") or "")

            snippet_parts: list[str] = []
            if summary:
                snippet_parts.append(summary)
            if network:
                snippet_parts.append(f"Network: {network}")
            if genres:
                snippet_parts.append(f"Genres: {', '.join(genres)}")

            externals = show.get("externals") or {}
            rating = show.get("rating") or {}

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(snippet_parts),
                    source="tvmaze.com",
                    rank=i,
                    provider=self.name,
                    published_date=premiered,
                    extra={
                        "thumbnail_url": thumb,
                        "image_url": thumb,
                        "tvdb_id": externals.get("thetvdb"),
                        "imdb_id": externals.get("imdb"),
                        "genres": genres,
                        "status": str(show.get("status") or ""),
                        "network": network,
                        "premiered": premiered,
                        "runtime": show.get("runtime"),
                        "language": str(show.get("language") or ""),
                        "rating": rating.get("average"),
                        "country": self._show_country(show),
                    },
                ),
            )

        return ProviderResult(results=results)
