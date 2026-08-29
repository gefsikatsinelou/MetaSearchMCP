"""GDELT news search via the public, keyless DOC 2.0 API.

GDELT (gdeltproject.org, Global Database of Events, Language, and Tone)
indexes news articles from print, broadcast, and web sources worldwide,
translated into English, with 15-minute update frequency. Its public DOC 2.0
API requires no API key:

``GET https://api.gdeltproject.org/api/v2/doc/doc?query=QUERY&mode=artlist&format=json``

Each hit includes the headline, article URL, publishing domain, language,
source country, and the "seendate" timestamp. Parsing uses only the shared
httpx client from the base provider.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
# GDELT caps a single request at this many records.
_MAX_API_RESULTS = 250


class GDELTProvider(BaseProvider):
    """Search recent global news coverage indexed by GDELT.

    Uses the keyless DOC 2.0 ``artlist`` mode, which returns recent articles
    matching the query. Each hit carries the headline, article URL, publishing
    domain, language, source country, and a UTC "seendate" timestamp.
    """

    name = "gdelt"
    description = (
        "Search recent global news coverage via the GDELT Project, no API key required."
    )
    tags: ClassVar[list[str]] = ["news", "web"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _parse_seendate(value: object) -> str | None:
        """Convert a GDELT ``YYYYMMDDTHHMMSSZ`` seendate to YYYY-MM-DD."""
        if not value:
            return None
        text = str(value).strip()
        if len(text) >= 8 and text[:8].isdigit():
            return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        return None

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the DOC 2.0 response into structured search results."""
        results: list[SearchResult] = []
        for i, article in enumerate(data.get("articles") or [], start=1):
            if not isinstance(article, dict):
                continue
            title = self._clean_text(article.get("title"))
            url = self._clean_text(article.get("url"))
            if not title or not url:
                continue

            domain = self._clean_text(article.get("domain"))
            language = self._clean_text(article.get("language"))
            country = self._clean_text(article.get("sourcecountry"))
            seendate = self._parse_seendate(article.get("seendate"))

            snippet_parts: list[str] = []
            if domain:
                snippet_parts.append(f"Source: {domain}")
            if language:
                snippet_parts.append(f"Language: {language}")
            if country:
                snippet_parts.append(f"Country: {country}")

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(snippet_parts),
                    source=domain or "gdeltproject.org",
                    rank=i,
                    provider=self.name,
                    published_date=seendate,
                    extra={
                        "domain": domain,
                        "language": language,
                        "source_country": country,
                        "seendate": self._clean_text(article.get("seendate")),
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search GDELT for recent news articles matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": str(limit),
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)
