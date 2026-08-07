"""CourtListener legal opinion search via the keyless Free Law Project API.

CourtListener (courtlistener.com, a Free Law Project service) indexes millions
of US federal and state court opinions. Its public REST API requires no API
key for anonymous use:

``GET https://www.courtlistener.com/api/rest/v4/search/?q=QUERY&page_size=N``

Each hit includes the case name, opinion landing-page URL, citations, court,
docket number, judge, filing date, and status. Parsing uses only the shared
httpx client from the base provider.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://www.courtlistener.com/api/rest/v4/search"
# The search endpoint ignores page_size (cursor-based pagination) and always
# returns up to this many items per request; results are truncated client-side.
_MAX_API_RESULTS = 20


class CourtListenerProvider(BaseProvider):
    """Search US court opinions and legal cases via CourtListener.

    Uses the keyless public REST API from Free Law Project, which indexes
    federal and state court opinions. Each hit carries the case name,
    landing-page URL, citations, court, docket number, judge, filing date,
    and status.
    """

    name = "courtlistener"
    description = (
        "Search US court opinions and legal cases via CourtListener "
        "(Free Law Project), no API key required."
    )
    tags: ClassVar[list[str]] = ["legal", "academic", "web"]

    @staticmethod
    def _clean_text(value: Any) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _citation_label(citations: Any) -> str:
        """Join the citation list into a single human-readable label."""
        if not citations:
            return ""
        return "; ".join(str(c) for c in citations if str(c).strip())

    def _parse(self, data: dict[str, Any], limit: int | None = None) -> ProviderResult:
        """Parse the CourtListener API response into structured results."""
        results: list[SearchResult] = []
        items = data.get("results") or []
        if limit is not None:
            items = items[:limit]

        for i, item in enumerate(items, start=1):
            case_name = self._clean_text(item.get("caseName"))
            absolute_url = item.get("absolute_url") or ""
            if not case_name or not absolute_url:
                continue
            url = f"https://www.courtlistener.com{absolute_url}"

            citation = self._citation_label(item.get("citation"))
            court = self._clean_text(item.get("court"))
            docket = self._clean_text(item.get("docketNumber"))
            judge = self._clean_text(item.get("judge"))
            status = self._clean_text(item.get("status"))
            neutral_cite = self._clean_text(item.get("neutralCite"))

            snippet_parts: list[str] = []
            if citation:
                snippet_parts.append(citation)
            elif neutral_cite:
                snippet_parts.append(neutral_cite)
            if court:
                snippet_parts.append(f"Court: {court}")
            if docket:
                snippet_parts.append(f"Docket: {docket}")
            if judge:
                snippet_parts.append(f"Judge: {judge}")
            if status:
                snippet_parts.append(f"Status: {status}")

            # Prefer the first opinion's direct PDF when available.
            download_url = ""
            opinions = item.get("opinions") or []
            if opinions and isinstance(opinions[0], dict):
                download_url = opinions[0].get("download_url") or ""

            results.append(
                SearchResult(
                    title=case_name or url,
                    url=url,
                    snippet=" | ".join(snippet_parts),
                    source="courtlistener.com",
                    rank=i,
                    provider=self.name,
                    published_date=self._iso_date_prefix(item.get("dateFiled")),
                    extra={
                        "court": court,
                        "court_citation": item.get("court_citation_string") or "",
                        "docket_number": docket,
                        "judge": judge,
                        "status": status,
                        "citations": item.get("citation") or [],
                        "neutral_cite": neutral_cite,
                        "cite_count": item.get("citeCount") or 0,
                        "date_argued": self._iso_date_prefix(item.get("dateArgued")),
                        "download_url": download_url,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search CourtListener for US court opinions matching *query*.

        Note: the CourtListener search API ignores ``page_size`` (pagination is
        cursor-based), so the response is truncated client-side to the
        requested result count.
        """
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {
            "q": query,
            "page_size": str(limit),
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
