"""Grants.gov federal funding-opportunity search via the keyless public API.

Grants.gov is the U.S. government's single portal for discretionary federal
funding: it publishes the funding opportunities of every awarding agency --
NIH, NSF, DARPA, NOAA, the Department of Education, the National Endowment for
the Humanities and many more.  An opportunity record carries its number and
title, the publishing agency, its status (``posted`` = open for applications,
``forecasted`` = announced for a later release, ``closed``, ``archived``), the
day applications open and the deadline, the Catalog of Federal Domestic
Assistance (CFDA) programme numbers, the funding instruments (grant,
cooperative agreement, procurement contract), the expected number of awards,
and the applicant types that are eligible to apply.

The search endpoint is public and keyless; it takes a JSON ``POST`` request::

    POST https://api.grants.gov/v1/api/search2
    {"keyword": QUERY, "rows": N, "oppStatuses": "forecasted|posted"}

The response is ``{"errorcode": 0, "msg": ..., "data": {"hitCount": <total>,
"oppHits": [...]}}``, ordered by the portal's relevance ranking.  Search hits
are thin, so the synopsis of the leading hits is fetched from the companion
keyless detail endpoint to recover each opportunity's description and award
range::

    POST https://api.grants.gov/v1/api/fetchOpportunity
    {"opportunityId": ID}

A failing detail lookup only costs that one hit its description; the hit itself
is still reported with the fields the search returned.  This complements the
literature, award and legal providers by answering which calls for proposals
are open right now, which agency runs them, how much they award and until when
applications can be submitted.  No API key is required.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, ClassVar
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://api.grants.gov/v1/api/search2"
_DETAIL_URL = "https://api.grants.gov/v1/api/fetchOpportunity"
# Public page of a single opportunity, keyed by the API's opportunity id.
_OPPORTUNITY_PAGE_URL = "https://www.grants.gov/search-results-detail/"
# Default status filter: only opportunities a searcher can still act on.
_OPEN_STATUSES = "forecasted|posted"
# The API pages its result lists; keep pages small for agents.
_MAX_API_RESULTS = 50
# Opportunities whose synopsis is fetched -- every detail costs one request.
_DETAIL_LIMIT = 5
# Characters of the opportunity synopsis copied into the snippet.
_SNIPPET_SYNOPSIS_LENGTH = 180
# CFDA numbers, funding instruments and applicant types listed in a snippet.
_SNIPPET_CFDA_LIMIT = 3
_SNIPPET_INSTRUMENT_LIMIT = 3
_SNIPPET_ELIGIBILITY_LIMIT = 3
# Search hits carry their dates as MM/DD/YYYY.
_US_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


class GrantsGovProvider(BaseProvider):
    """Search Grants.gov for U.S. federal funding opportunities.

    Keyless.  Queries the Grants.gov search API and returns one hit per
    opportunity, carrying its number, title, agency, status, open and close
    dates, CFDA programme numbers, award range, funding instruments and
    eligible applicant types, and linking to the opportunity page on
    grants.gov.  The description of the leading hits is fetched separately so
    that a slow or failing detail lookup never hides the search results.
    """

    name = "grants_gov"
    description = (
        "Search Grants.gov — U.S. federal funding opportunities (grants, "
        "cooperative agreements, contracts: title, description, agency, "
        "status, deadline, award ceiling/floor, eligibility) via the "
        "keyless search API."
    )
    tags: ClassVar[list[str]] = ["academic", "gov", "funding", "web"]

    @staticmethod
    def _text(value: object) -> str:
        """Return a free-text field with HTML markup and extra blanks removed."""
        if not isinstance(value, str) or not value.strip():
            return ""
        return _clean(BeautifulSoup(value, "lxml").get_text(" ", strip=True))

    @staticmethod
    def _date(value: object) -> str:
        """Convert the API's ``MM/DD/YYYY`` date to ``YYYY-MM-DD``.

        Values that are not dates (empty strings, ``"none"``, other formats)
        are reported as an empty string.
        """
        if not isinstance(value, str):
            return ""
        match = _US_DATE.match(value.strip())
        if match is None:
            return ""
        month, day, year = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"

    @staticmethod
    def _integer(value: object) -> int | None:
        """Return a dollar amount or award count as an integer.

        The API mixes integers, numeric strings and the sentinel ``"none"``
        for fields that were never filled in; anything that is not a number is
        dropped.
        """
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            digits = value.strip().replace(",", "").replace("$", "")
            if digits.isdigit():
                return int(digits)
        return None

    @classmethod
    def _names(cls, value: object, limit: int) -> list[str]:
        """Return the description of the first *limit* labelled records.

        The API models funding instruments and applicant types as lists of
        ``{"id": ..., "description": ...}`` mappings.
        """
        if not isinstance(value, list):
            return []
        names: list[str] = []
        for entry in value:
            if not isinstance(entry, dict):
                continue
            label = _clean(entry.get("description") or entry.get("id"))
            if label and label not in names:
                names.append(label)
            if len(names) >= limit:
                break
        return names

    @classmethod
    def _cfda_numbers(cls, hit: dict[str, Any]) -> list[str]:
        """Return the distinct CFDA programme numbers of an opportunity."""
        raw = hit.get("cfdaList")
        if not isinstance(raw, list):
            return []
        numbers: list[str] = []
        for entry in raw:
            number = _clean(entry)
            if number and number not in numbers:
                numbers.append(number)
        return numbers

    @staticmethod
    def _award_range(ceiling: int | None, floor: int | None) -> str:
        """Format the award range as e.g. ``$100,000 - $3,500,000``."""
        if ceiling and floor and ceiling != floor:
            return f"${floor:,} - ${ceiling:,}"
        if ceiling:
            return f"Up to ${ceiling:,}"
        if floor:
            return f"From ${floor:,}"
        return ""

    @staticmethod
    def _snippet(
        description: str,
        agency: str,
        status: str,
        close_date: str,
        award_range: str,
        instruments: list[str],
        eligibilities: list[str],
    ) -> str:
        """Compose the snippet for a single funding opportunity."""
        parts: list[str] = []
        if description:
            parts.append(description[:_SNIPPET_SYNOPSIS_LENGTH])
        if agency:
            parts.append(f"Agency: {agency}")
        if status:
            parts.append(f"Status: {status}")
        if close_date:
            parts.append(f"Closes: {close_date}")
        if award_range:
            parts.append(f"Award: {award_range}")
        if instruments:
            parts.append(f"Instruments: {', '.join(instruments)}")
        if eligibilities:
            parts.append(f"Eligible: {', '.join(eligibilities)}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        hit: dict[str, Any],
        synopsis: dict[str, Any] | None,
        rank: int,
        total: int | None,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a search hit and its synopsis."""
        title = _clean(hit.get("title"))
        opportunity_id = _clean(hit.get("id"))
        if not title or not opportunity_id:
            return None

        synopsis = synopsis or {}
        number = _clean(hit.get("number"))
        agency = _clean(hit.get("agency"))
        agency_code = _clean(hit.get("agencyCode"))
        status = _clean(hit.get("oppStatus"))
        document_type = _clean(hit.get("docType"))
        open_date = self._date(hit.get("openDate"))
        close_date = self._date(hit.get("closeDate"))
        cfda_numbers = self._cfda_numbers(hit)

        description = self._text(synopsis.get("synopsisDesc"))
        instruments = self._names(
            synopsis.get("fundingInstruments"),
            _SNIPPET_INSTRUMENT_LIMIT,
        )
        eligibilities = self._names(
            synopsis.get("applicantTypes"),
            _SNIPPET_ELIGIBILITY_LIMIT,
        )
        ceiling = self._integer(synopsis.get("awardCeiling"))
        floor = self._integer(synopsis.get("awardFloor"))
        expected_awards = self._integer(synopsis.get("numberOfAwards"))
        raw_cost_sharing = synopsis.get("costSharing")
        cost_sharing = raw_cost_sharing if isinstance(raw_cost_sharing, bool) else None

        return SearchResult(
            title=title,
            url=f"{_OPPORTUNITY_PAGE_URL}{quote(opportunity_id)}",
            snippet=self._snippet(
                description,
                agency or agency_code,
                status,
                close_date,
                self._award_range(ceiling, floor),
                instruments,
                eligibilities,
            ),
            source="grants.gov",
            rank=rank,
            provider=self.name,
            published_date=open_date or None,
            extra={
                "opportunity_id": opportunity_id,
                "opportunity_number": number or None,
                "agency": agency or agency_code or None,
                "agency_code": agency_code or None,
                "status": status or None,
                "document_type": document_type or None,
                "open_date": open_date or None,
                "close_date": close_date or None,
                "cfda_numbers": cfda_numbers,
                "award_ceiling": ceiling,
                "award_floor": floor,
                "expected_awards": expected_awards,
                "cost_sharing": cost_sharing,
                "funding_instruments": instruments,
                "eligible_applicants": eligibilities,
                "description": description or None,
                "total_results": total,
            },
        )

    @classmethod
    def _hits(cls, data: object, limit: int) -> list[dict[str, Any]]:
        """Return the usable search hits, deduplicated by opportunity id."""
        if not isinstance(data, dict):
            return []
        payload = data.get("data")
        if not isinstance(payload, dict):
            return []
        items = payload.get("oppHits")
        if not isinstance(items, list):
            return []

        hits: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            if len(hits) >= limit:
                break
            if not isinstance(item, dict):
                continue
            opportunity_id = _clean(item.get("id"))
            # An opportunity is keyed by its API id.
            if not opportunity_id or opportunity_id in seen:
                continue
            if not _clean(item.get("title")):
                continue
            seen.add(opportunity_id)
            hits.append(item)
        return hits

    @staticmethod
    def _total(data: object) -> int | None:
        """Return the total number of matches reported by the API."""
        if not isinstance(data, dict):
            return None
        payload = data.get("data")
        if not isinstance(payload, dict):
            return None
        total = payload.get("hitCount")
        return total if isinstance(total, int) and not isinstance(total, bool) else None

    @staticmethod
    def _check_error(data: object) -> None:
        """Raise when the API reports an application-level error.

        Failures travel inside the payload as a non-zero ``errorcode`` with a
        human-readable ``msg``; they are surfaced as a provider error rather
        than as an empty result page.
        """
        if not isinstance(data, dict):
            return
        errorcode = data.get("errorcode")
        if errorcode in (0, None):
            return
        message = _clean(data.get("msg")) or "search failed"
        raise RuntimeError(f"grants.gov rejected the search: {message}")

    @staticmethod
    def _synopsis(payload: object) -> dict[str, Any] | None:
        """Return the synopsis mapping of an opportunity detail response."""
        if not isinstance(payload, dict):
            return None
        if payload.get("errorcode") not in (0, None):
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        synopsis = data.get("synopsis")
        if not isinstance(synopsis, dict):
            return None
        return synopsis

    async def _fetch_synopses(
        self,
        client: httpx.AsyncClient,
        opportunity_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Fetch the synopsis of every id, ignoring individual failures.

        Details are a best-effort enrichment: a request that fails or answers
        with an unexpected shape simply leaves the corresponding hit without a
        description.
        """
        if not opportunity_ids:
            return {}

        async def _one(opportunity_id: str) -> tuple[str, object]:
            resp = await client.post(
                _DETAIL_URL,
                json={"opportunityId": opportunity_id},
            )
            resp.raise_for_status()
            return opportunity_id, resp.json()

        payloads = await asyncio.gather(
            *(_one(opportunity_id) for opportunity_id in opportunity_ids),
            return_exceptions=True,
        )

        synopses: dict[str, dict[str, Any]] = {}
        for entry in payloads:
            if isinstance(entry, BaseException):
                continue
            opportunity_id, payload = entry
            synopsis = self._synopsis(payload)
            if synopsis:
                synopses[opportunity_id] = synopsis
        return synopses

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Grants.gov for funding opportunities matching *query*.

        Only forecasted and posted opportunities are requested, so the results
        are ones a searcher can still act on.  A blank query performs no
        request.  The portal's relevance ranking is preserved.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {
            "keyword": cleaned,
            "rows": limit,
            "oppStatuses": _OPEN_STATUSES,
        }

        async with self._client() as client:
            resp = await client.post(_SEARCH_URL, json=payload)
            resp.raise_for_status()

            data: object = resp.json()
            self._check_error(data)
            hits = self._hits(data, limit)
            if not hits:
                return ProviderResult(results=[])
            total = self._total(data)

            synopses = await self._fetch_synopses(
                client,
                [_clean(hit.get("id")) for hit in hits[:_DETAIL_LIMIT]],
            )

        results: list[SearchResult] = []
        for hit in hits:
            built = self._build_result(
                hit,
                synopses.get(_clean(hit.get("id"))),
                len(results) + 1,
                total,
            )
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)
