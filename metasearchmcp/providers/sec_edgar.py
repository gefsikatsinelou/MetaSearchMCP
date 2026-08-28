"""SEC EDGAR full-text search and company filings via the keyless public APIs.

Two complementary keyless endpoints from the U.S. Securities and Exchange
Commission:

1. **Full-text search** — ``https://efts.sec.gov/LATEST/search-index``
   indexes filing documents (form types, display names, CIK, dates) and
   supports ``q``/``forms`` filters.

2. **Company filings** — ``https://data.sec.gov/submissions/CIK######.json``
   returns the 1000 most recent filings for a company identified by a
   10-digit zero-padded CIK.

Both endpoints are governed by SEC's fair-access policy: they are public,
require no API key, and ask for a descriptive ``User-Agent`` identifying
the requester. The provider derives a per-company EDGAR filing URL from the
accession number for every hit.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_FTS_URL = "https://efts.sec.gov/LATEST/search-index"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
# Browser-like headers are required: SEC returns 403 for default bot user
# agents, and the FTS endpoint applies aggressive anti-bot rules.
_SEC_HEADERS: ClassVar[dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.5",
}
_EDGAR_BROWSE_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
)
# Forms whose full-text hits are document exhibits (EX-*) rather than the
# primary filing; they are skipped in favor of the primary document.
_EXHIBIT_PREFIX = "EX-"
_MAX_FILINGS_PER_COMPANY = 10
_MAX_FTS_RESULTS = 50


class SecEdgarProvider(BaseProvider):
    """Search U.S. SEC EDGAR filings by company name, ticker, or keyword.

    Keyless. Uses the SEC full-text search index and the company submissions
    API. Results carry the filing form type, company display name, filing
    date, and a direct EDGAR document link.
    """

    name = "sec_edgar"
    description = (
        "Search U.S. SEC EDGAR filings by company, ticker, or keyword — "
        "forms like 10-K, 8-K, and 10-Q via the keyless SEC public APIs."
    )
    tags: ClassVar[list[str]] = ["finance", "regulatory", "us"]

    def is_available(self) -> bool:
        """Return whether SEC EDGAR is enabled via unstable-provider flag."""
        from metasearchmcp.config import get_settings

        return get_settings().allow_unstable_providers

    def _sec_client(self):
        """Return an HTTP client with SEC's required browser-like headers."""
        import httpx

        return httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            headers=_SEC_HEADERS,
        )

    @staticmethod
    def _company_name(display_names: Any, ciks: Any) -> str:
        """Extract a readable company name from a search-index hit."""
        names = display_names or []
        if names:
            return str(names[0]).split("  (CIK")[0].strip()
        cik = (ciks or [None])[0]
        return f"CIK {cik}" if cik else "Unknown company"

    @staticmethod
    def _is_exhibit(file_type: str) -> bool:
        """Return True for exhibit (EX-*) types that are not primary filings."""
        return file_type.upper().startswith(_EXHIBIT_PREFIX)

    def _parse_fts(self, data: dict[str, Any], limit: int) -> ProviderResult:
        """Parse the full-text search response into structured results."""
        results: list[SearchResult] = []
        for hit in (data.get("hits") or {}).get("hits") or []:
            if len(results) >= limit:
                break
            source = hit.get("_source") or {}
            if not isinstance(source, dict):
                continue
            form = source.get("form") or source.get("file_type") or ""
            if not form or self._is_exhibit(form):
                continue
            display_names = source.get("display_names") or []
            ciks = source.get("ciks") or []
            if not display_names and not ciks:
                continue
            cik = str((ciks or [""])[0])
            accession = source.get("adsh") or ""
            if not accession:
                continue
            primary = (
                source.get("primary_document") or source.get("file_description") or ""
            )
            file_date = source.get("file_date") or ""
            period_ending = source.get("period_ending") or ""

            url = _EDGAR_BROWSE_URL.format(cik=cik)
            if primary:
                url = (
                    "https://www.sec.gov/Archives/edgar/data/"
                    f"{cik}/{accession.replace('-', '')}/{quote(primary)}"
                )

            snippet_parts: list[str] = []
            if period_ending:
                snippet_parts.append(f"Period ending: {period_ending}")
            if source.get("biz_locations"):
                snippet_parts.append(f"Location: {source['biz_locations'][0]}")
            snippet = " | ".join(snippet_parts)

            results.append(
                SearchResult(
                    title=f"{self._company_name(display_names, ciks)} — {form}",
                    url=url,
                    snippet=snippet,
                    source="sec.gov",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=file_date or None,
                    extra={
                        "cik": cik,
                        "form": form,
                        "accession_number": accession,
                        "filing_date": file_date,
                        "period_ending": period_ending,
                        "primary_document": primary,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def _search_full_text(self, query: str, limit: int) -> ProviderResult:
        """Query the SEC full-text search index for *query*."""
        async with self._sec_client() as client:
            resp = await client.get(
                _FTS_URL,
                params={
                    "q": query,
                    "page_size": str(min(limit, _MAX_FTS_RESULTS)),
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse_fts(data, limit)

    def _parse_filings(self, data: dict[str, Any], limit: int) -> ProviderResult:
        """Parse a company submissions payload into structured results."""
        results: list[SearchResult] = []
        company = data.get("name") or ""
        cik = str(data.get("cik") or "")
        if not company and not cik:
            return ProviderResult(results=results)

        recent = (data.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        dates = recent.get("filingDate") or []
        accessions = recent.get("accessionNumber") or []
        docs = recent.get("primaryDocument") or []
        report_dates = recent.get("reportDate") or []

        for i, form in enumerate(forms):
            if len(results) >= limit:
                break
            if not form or self._is_exhibit(form):
                continue
            accession = accessions[i] if i < len(accessions) else ""
            primary = docs[i] if i < len(docs) else ""
            if not accession or not primary:
                continue

            filing_date = dates[i] if i < len(dates) else ""
            report_date = report_dates[i] if i < len(report_dates) else ""
            url = (
                "https://www.sec.gov/Archives/edgar/data/"
                f"{cik}/{accession.replace('-', '')}/{quote(primary)}"
            )

            snippet_parts: list[str] = []
            if report_date:
                snippet_parts.append(f"Report date: {report_date}")
            snippet = " | ".join(snippet_parts)

            results.append(
                SearchResult(
                    title=f"{company} — {form}",
                    url=url,
                    snippet=snippet,
                    source="sec.gov",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=filing_date or None,
                    extra={
                        "cik": cik,
                        "form": form,
                        "accession_number": accession,
                        "filing_date": filing_date,
                        "report_date": report_date,
                        "primary_document": primary,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def _search_company(self, query: str, limit: int) -> ProviderResult:
        """Resolve *query* to a company CIK and return its recent filings."""
        async with self._sec_client() as client:
            resp = await client.get(
                _FTS_URL,
                params={"q": query, "page_size": "1"},
            )
            resp.raise_for_status()
            data = resp.json()

        cik: str = ""
        for hit in (data.get("hits") or {}).get("hits") or []:
            source = hit.get("_source") or {}
            ciks = source.get("ciks") or []
            if ciks:
                cik = str(ciks[0])
                break
        if not cik:
            return ProviderResult(results=[])

        async with self._sec_client() as client:
            resp = await client.get(_SUBMISSIONS_URL.format(cik=int(cik)))
            resp.raise_for_status()
            filings = resp.json()

        return self._parse_filings(filings, limit)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search SEC EDGAR for *query* and return filing results.

        A query that looks like a company identifier (ticker-like token of
        1-5 uppercase letters, a CIK number, or a quoted company name) is
        first resolved to a company and its recent filings are returned;
        otherwise the full-text index is searched.
        """
        limit = min(params.num_results, self._max_results)
        # The FTS index's display names do NOT carry the (TICKER) suffix;
        # company-resolution is only attempted when the query is clearly a
        # ticker/CIK or a quoted exact company name.
        token = query.strip()
        looks_like_ticker = 1 <= len(token) <= 5 and token.isalpha() and token.isupper()
        if (
            looks_like_ticker
            or token.isdigit()
            or (token.startswith('"') and token.endswith('"'))
        ):
            result = await self._search_company(query, limit)
            if result.results:
                return result

        return await self._search_full_text(query, limit)
