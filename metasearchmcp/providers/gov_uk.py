"""GOV.UK content search via the keyless public Search API.

``GET https://www.gov.uk/api/search.json`` returns GOV.UK pages that match a
query: guidance, publications, announcements, consultations, and detailed
guides published by UK government departments and public bodies. No API key
or authentication is required.

Each hit carries the page title, link, description, document format, owning
organisations, world locations, and the last public update timestamp.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://www.gov.uk/api/search.json"
_BASE_SITE = "https://www.gov.uk"
# The Search API caps the requestable page size; keep a conservative limit.
_MAX_API_RESULTS = 50
# Keep description previews short in the snippet field.
_DESCRIPTION_PREVIEW = 300
# Cap the number of organisations listed in a snippet.
_MAX_SNIPPET_ORGS = 3


class GovUkProvider(BaseProvider):
    """Search GOV.UK for UK government guidance, publications, and news.

    Uses the official keyless ``www.gov.uk/api/search.json`` endpoint, which
    requires no authentication and returns structured metadata: title, link,
    description, format, organisations, world locations, and update time.
    """

    name = "gov_uk"
    description = (
        "Search GOV.UK — UK government guidance, publications, and "
        "announcements via the keyless GOV.UK Search API."
    )
    tags: ClassVar[list[str]] = ["web", "gov", "knowledge"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _organisations(item: dict[str, Any]) -> list[str]:
        """Return the titles of organisations that own an item, in order."""
        organisations: list[str] = []
        for org in item.get("organisations") or []:
            if not isinstance(org, dict):
                continue
            title = GovUkProvider._clean(org.get("title"))
            if title and title not in organisations:
                organisations.append(title)
        return organisations

    def _parse(self, data: Any, limit: int) -> ProviderResult:
        """Parse the /search.json response into structured search results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        items = data.get("results")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        for i, item in enumerate(items[:limit], start=1):
            if not isinstance(item, dict):
                continue

            title = self._clean(item.get("title"))
            link = str(item.get("link") or "")
            if not title or not link:
                continue

            url = link if link.startswith("http") else f"{_BASE_SITE}{link}"
            description = self._clean(item.get("description"))
            fmt = self._clean(item.get("format"))
            organisations = self._organisations(item)
            world_locations = [
                str(loc)
                for loc in (item.get("world_locations") or [])
                if isinstance(loc, str)
            ]

            snippet_parts: list[str] = []
            if description:
                snippet_parts.append(description[:_DESCRIPTION_PREVIEW])
            if fmt:
                snippet_parts.append(f"Format: {fmt}")
            if organisations:
                snippet_parts.append(
                    "Organisations: " + ", ".join(organisations[:_MAX_SNIPPET_ORGS]),
                )

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(snippet_parts),
                    source="gov.uk",
                    rank=i,
                    provider=self.name,
                    published_date=self._iso_date_prefix(
                        item.get("public_timestamp"),
                    ),
                    extra={
                        "format": fmt,
                        "document_type": self._clean(item.get("document_type")),
                        "organisations": organisations,
                        "world_locations": world_locations,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search GOV.UK for pages matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={"q": query, "count": str(limit)},
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit)
