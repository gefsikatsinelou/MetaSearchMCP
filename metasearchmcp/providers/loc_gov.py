"""Library of Congress search via the public, keyless loc.gov JSON API.

The Library of Congress (loc.gov) is the largest library in the world and
offers an open, keyless JSON search endpoint over its digital collections:

``GET https://www.loc.gov/search/?q=QUERY&fo=json&c=N``

``fo=json`` returns a machine-readable document whose ``results`` array
covers all collection formats — books, manuscripts, photos, maps, films,
newspapers, and web archives. Each hit carries the title, a canonical
record URL (item/collection page), the primary date, format labels,
subjects, and a free-text description. The ``search.hits`` field reports
the overall match count, and ``pagination.of`` the result total.

The provider is keyless, uses only the shared httpx client, and tags
itself ``archive``/``knowledge`` so it can be discovered via the
``list_providers`` tool and targeted through ``search_web`` tag filters.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://www.loc.gov/search/"
# loc.gov caps a single listing request at 100 items per page.
_MAX_API_RESULTS = 100


class LocGovProvider(BaseProvider):
    """Search the Library of Congress digital collections.

    Keyless. Uses the public JSON search endpoint over the full loc.gov
    index (books, manuscripts, photos, maps, films, newspapers, web
    archives). Each result carries the record title, canonical URL,
    primary date, format labels, subjects, and a free-text description.
    """

    name = "loc_gov"
    description = (
        "Search the Library of Congress digital collections "
        "(books, manuscripts, photos, maps, films, newspapers), "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["archive", "knowledge", "web"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _first_string(value: object) -> str:
        """Return the first non-empty string from a scalar, list, or None."""
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return item.strip()
            return ""
        return LocGovProvider._clean_text(value)

    @staticmethod
    def _clean_list(value: object) -> list[str]:
        """Return a deduplicated list of non-empty, stripped strings."""
        if not isinstance(value, list):
            return []
        seen: set[str] = set()
        cleaned: list[str] = []
        for item in value:
            text = LocGovProvider._clean_text(item)
            if text and text.lower() not in seen:
                seen.add(text.lower())
                cleaned.append(text)
        return cleaned

    def _parse(
        self,
        data: dict[str, Any],
        max_results: int | None = None,
    ) -> ProviderResult:
        """Parse the loc.gov JSON response into structured search results."""
        results: list[SearchResult] = []
        limit = max_results or self._max_results
        hits = data.get("results") or []
        if not isinstance(hits, list):
            hits = []

        for hit in hits:
            if not isinstance(hit, dict):
                continue
            title = self._clean_text(hit.get("title"))
            url = self._first_string(hit.get("url"))
            if not title or not url:
                continue

            description = self._clean_text(
                self._first_string(hit.get("description")),
            )
            date = self._first_string(hit.get("date")) or self._iso_date_prefix(
                self._first_string(hit.get("timestamp")),
            )
            formats = self._clean_list(hit.get("original_format"))
            subjects = self._clean_list(hit.get("subject"))
            online_formats = self._clean_list(hit.get("online_format"))

            snippet_parts: list[str] = []
            if description:
                snippet_parts.append(description[:MAX_SNIPPET_LENGTH])
            if formats:
                snippet_parts.append(f"Format: {', '.join(formats[:3])}")
            if subjects:
                snippet_parts.append(f"Subjects: {', '.join(subjects[:5])}")

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(snippet_parts),
                    source="loc.gov",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=date or None,
                    extra={
                        "formats": formats,
                        "subjects": subjects,
                        "online_formats": online_formats,
                        "date": date,
                        "id": self._first_string(hit.get("id")),
                    },
                ),
            )
            if len(results) >= limit:
                break

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the Library of Congress digital collections for *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {
            "q": query,
            "fo": "json",
            "c": str(limit),
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, max_results=limit)
