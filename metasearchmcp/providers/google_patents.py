"""Google Patents search — patent and patent-application search via the public XHR API.

Google Patents indexes granted patents and published applications from
patent offices worldwide (USPTO, EPO, WIPO, JPO, KIPO, and more). Its
read-only XHR query endpoint requires no API key:

``GET https://patents.google.com/xhr/query?url=q%3DQUERY&exp=``

Each hit exposes the publication number, title, snippet (usually the first
claim), inventors, assignee, and key dates. Results link to the patent
landing page on Google Patents.
"""

from __future__ import annotations

from typing import Any, ClassVar

from bs4 import BeautifulSoup

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://patents.google.com/xhr/query"
_PATENT_URL = "https://patents.google.com/patent/{number}/en"


class GooglePatentsProvider(BaseProvider):
    """Search patents and patent applications indexed by Google Patents.

    Keyless. Uses the read-only XHR query endpoint; the browser-like
    scraper client is required because the endpoint rejects plain bot
    user agents. Each result carries the publication number, inventors,
    assignee, and priority/grant dates, linked to the Google Patents
    landing page.
    """

    name = "google_patents"
    description = (
        "Search patents and patent applications worldwide via Google Patents, "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "patents", "academic"]

    @staticmethod
    def _clean_html(value: object) -> str:
        """Strip HTML tags and entities from a patent title or snippet.

        Tag boundaries are joined without a separator so inline markup
        like ``<b>CRISPR</b>-Cas`` yields ``CRISPR-Cas`` rather than
        ``CRISPR -Cas``; runs of whitespace are collapsed.
        """
        if not value:
            return ""
        text = BeautifulSoup(str(value), "lxml").get_text("", strip=False)
        return " ".join(text.split())

    def _parse(
        self,
        data: dict[str, Any],
        max_results: int | None = None,
    ) -> ProviderResult:
        """Parse the Google Patents XHR response into structured results."""
        results: list[SearchResult] = []
        limit = max_results or self._max_results
        clusters = (data.get("results") or {}).get("cluster") or []

        for cluster in clusters:
            for entry in cluster.get("result") or []:
                patent = entry.get("patent") or {}
                number = patent.get("publication_number") or ""
                if not number:
                    continue
                title = self._clean_html(patent.get("title"))
                if not title:
                    continue

                snippet = self._clean_html(patent.get("snippet"))
                inventors = self._clean_html(patent.get("inventor"))
                assignee = self._clean_html(patent.get("assignee"))
                snippet_parts: list[str] = []
                if inventors:
                    snippet_parts.append(f"Inventors: {inventors}")
                if assignee:
                    snippet_parts.append(f"Assignee: {assignee}")
                if snippet_parts:
                    suffix = " | ".join(snippet_parts)
                    snippet = f"{snippet} | {suffix}" if snippet else suffix

                grant_date = (
                    patent.get("grant_date") or patent.get("publication_date") or ""
                )

                results.append(
                    SearchResult(
                        title=title,
                        url=_PATENT_URL.format(number=number),
                        snippet=snippet,
                        source="patents.google.com",
                        rank=len(results) + 1,
                        provider=self.name,
                        published_date=grant_date or None,
                        extra={
                            "publication_number": number,
                            "inventors": inventors,
                            "assignee": assignee,
                            "language": patent.get("language") or "",
                            "filing_date": patent.get("filing_date") or "",
                            "grant_date": grant_date,
                            "priority_date": patent.get("priority_date") or "",
                        },
                    ),
                )
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Google Patents for *query* and return patent results."""
        limit = min(params.num_results, self._max_results)
        payload = {"url": f"q={query}", "exp": ""}
        async with self._scraper_client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, max_results=limit)
