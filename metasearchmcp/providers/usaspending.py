"""U.S. federal spending search via the keyless USAspending awards API.

``USAspending.gov`` is the official open-data source for how the U.S. federal
government spends money: the awards (contracts, grants, loans, other financial
assistance) it makes every fiscal year.  Its award search endpoint is public
and keyless and takes the query as a JSON body::

    POST https://api.usaspending.gov/api/v2/search/spending_by_award/
    {"filters": {"keywords": ["QUERY"],
                 "award_type_codes": ["02", "03", "04", "05"]},
     "fields": ["Award ID", "Recipient Name", "Award Amount", ...],
     "page": 1, "limit": N, "sort": "Award Amount", "order": "desc",
     "subawards": false}

Every award record carries its award id, the recipient organisation, the
awarded amount, the award's description, start and end dates, the awarding and
funding agencies and sub-agencies, and the award type (the contract type such
as ``DEFINITIVE CONTRACT`` for procurement and the assistance type such as
``PROJECT GRANT (B)`` for grants).

The response is::

    {"spending_level": "awards", "limit": N, "results": [...],
     "page_metadata": {"page": 1, "hasNext": false}, "messages": [...]}

ordered by the requested sort key (here the awarded amount, descending).

The API only accepts award type codes coming from a single group per request
(it rejects a mixed request with HTTP 422 and ``'award_type_codes' must only
contain types from one group``), so contracts and grants are queried as two
separate requests whose results are merged.  This complements the other
funding providers: Grants.gov covers the funding opportunities agencies
publish, NIH RePORTER covers NIH projects, NSF Awards covers the NSF's own
award records, and this provider covers the award and contract records of
every federal agency.  No API key is required.
"""

from __future__ import annotations

import math
from typing import Any, ClassVar
from urllib.parse import quote, quote_plus

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
# Public award page, keyed by the API's ``generated_internal_id``.
_AWARD_PAGE_URL = "https://www.usaspending.gov/award/"
# Fallback site search used for the rare hit without a generated id.
_SEARCH_PAGE_URL = "https://www.usaspending.gov/search"
_SOURCE = "usaspending.gov"
# Largest number of award records the API returns per request.
_MAX_API_RESULTS = 100
# Award amounts are requested through this field, which must therefore also be
# the sort field: the API rejects a sort key that is not among the fields.
_SORT_FIELD = "Award Amount"

# Award type codes, grouped exactly as the API groups them.  A request may only
# carry codes from one group, so each group is queried separately and the
# requested result count is split between them.
_AWARD_TYPE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("contracts", ("A", "B", "C", "D")),
    ("grants", ("02", "03", "04", "05")),
)

# Fields requested for every award, keeping the payload small while covering
# the award's identity, recipient, money, agency and dates.
_FIELDS: tuple[str, ...] = (
    "Award ID",
    "Recipient Name",
    "Award Amount",
    "Description",
    "Start Date",
    "End Date",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Funding Agency",
    "Award Type",
    "Contract Award Type",
    "generated_internal_id",
    "recipient_id",
    "agency_slug",
)

# Characters of the award description copied into the snippet.
_SNIPPET_DESCRIPTION_LENGTH = 180
# Characters of the description used as a title when an award has no recipient.
_TITLE_DESCRIPTION_LENGTH = 80
# Length of the ``YYYY-MM-DD`` date prefix the API returns.
_DATE_LENGTH = 10


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _amount(value: object) -> float | None:
    """Return a numeric award amount, ignoring booleans and junk values.

    The API sends amounts sometimes as JSON numbers and sometimes as strings,
    the latter optionally carrying thousands separators and a currency sign.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("$", "")
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _money(value: float | None) -> str:
    """Format an award amount as e.g. ``$67,372,443``; blank when not numeric."""
    return f"${value:,.0f}" if value is not None else ""


def _date(value: object) -> str | None:
    """Return a ``YYYY-MM-DD`` award date, or ``None`` when absent."""
    text = _clean(value)[:_DATE_LENGTH]
    return text or None


class UsaSpendingProvider(BaseProvider):
    """Search U.S. federal awards (contracts and grants) on USAspending.gov.

    Keyless.  *query* is matched against the award description, the recipient
    and the agency metadata, and awards come back ordered by awarded amount.
    Results are split between contracts and grants so both kinds of federal
    spending are represented, and each hit carries the award id, recipient,
    amount, agency, dates and award type, linking to the award page on
    usaspending.gov.
    """

    name = "usaspending"
    description = (
        "Search USAspending.gov — U.S. federal awards and contracts (award id, "
        "recipient organisation, awarded amount, description, awarding and "
        "funding agency, award type, start/end dates) via the keyless federal "
        "spending API; no API key required."
    )
    tags: ClassVar[list[str]] = ["finance", "gov", "funding", "web"]

    @staticmethod
    def _award_url(hit: dict[str, Any]) -> str:
        """Return the award page URL of a hit.

        Awards are keyed by the API's ``generated_internal_id``; a hit without
        one falls back to a site search for its award id so a link is always
        returned.
        """
        internal = _clean(hit.get("generated_internal_id"))
        if internal:
            return f"{_AWARD_PAGE_URL}{quote(internal, safe='')}"
        award_id = _clean(hit.get("Award ID"))
        if award_id:
            return f"{_SEARCH_PAGE_URL}?keyword={quote_plus(award_id)}"
        return ""

    @staticmethod
    def _award_type(hit: dict[str, Any]) -> str:
        """Return the award's type label.

        Procurement rows expose their type in ``Contract Award Type`` and
        assistance rows in ``Award Type``; whichever the record carries wins.
        """
        for key in ("Award Type", "Contract Award Type"):
            label = _clean(hit.get(key))
            if label:
                return label
        return ""

    @staticmethod
    def _title(hit: dict[str, Any]) -> str:
        """Compose the title of an award from its recipient and award id.

        An award record has no title field of its own, so the recipient
        organisation and the award id identify it; a hit missing both falls
        back to an excerpt of the award description.
        """
        recipient = _clean(hit.get("Recipient Name"))
        award_id = _clean(hit.get("Award ID"))
        title = " — ".join(part for part in (recipient, award_id) if part)
        if title:
            return title
        return _clean(hit.get("Description"))[:_TITLE_DESCRIPTION_LENGTH]

    @staticmethod
    def _agency(hit: dict[str, Any]) -> str:
        """Return the awarding agency, qualified by its sub-agency."""
        agency = _clean(hit.get("Awarding Agency"))
        sub_agency = _clean(hit.get("Awarding Sub Agency"))
        if agency and sub_agency and sub_agency != agency:
            return f"{agency} ({sub_agency})"
        return agency or sub_agency

    @staticmethod
    def _period(start: str | None, end: str | None) -> str:
        """Join the award's start and end dates into a period."""
        return " to ".join(part for part in (start, end) if part)

    @staticmethod
    def _snippet(
        recipient: str,
        agency: str,
        amount: str,
        period: str,
        award_type: str,
        description: str,
    ) -> str:
        """Compose the snippet for a single award."""
        parts: list[str] = []
        if recipient:
            parts.append(f"Recipient: {recipient}")
        if agency:
            parts.append(agency)
        if amount:
            parts.append(f"Award: {amount}")
        if period:
            parts.append(period)
        if award_type:
            parts.append(award_type)
        if description:
            parts.append(description[:_SNIPPET_DESCRIPTION_LENGTH])
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        hit: dict[str, Any],
        group: str,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw USAspending award record."""
        title = self._title(hit)
        url = self._award_url(hit)
        if not title or not url:
            return None

        recipient = _clean(hit.get("Recipient Name"))
        agency = _clean(hit.get("Awarding Agency"))
        sub_agency = _clean(hit.get("Awarding Sub Agency"))
        award_type = self._award_type(hit)
        amount = _amount(hit.get("Award Amount"))
        start = _date(hit.get("Start Date"))
        end = _date(hit.get("End Date"))
        description = _clean(hit.get("Description"))

        return SearchResult(
            title=title,
            url=url,
            snippet=self._snippet(
                recipient,
                self._agency(hit),
                _money(amount),
                self._period(start, end),
                award_type,
                description,
            ),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            published_date=start,
            extra={
                "award_id": _clean(hit.get("Award ID")) or None,
                "award_group": group,
                "recipient": recipient or None,
                "recipient_id": _clean(hit.get("recipient_id")) or None,
                "amount": amount,
                "award_type": award_type or None,
                "awarding_agency": agency or None,
                "awarding_sub_agency": sub_agency or None,
                "funding_agency": _clean(hit.get("Funding Agency")) or None,
                "start_date": start,
                "end_date": end,
                "description": description or None,
                "agency_slug": _clean(hit.get("agency_slug")) or None,
                "generated_internal_id": (
                    _clean(hit.get("generated_internal_id")) or None
                ),
            },
        )

    def _parse(self, data: object, group: str, limit: int) -> list[SearchResult]:
        """Parse an award search response into structured results.

        The API's amount-descending order is preserved and awards are
        deduplicated by their generated id.  Any other payload shape yields an
        empty result set.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return results
        hits = data.get("results")
        if not isinstance(hits, list):
            return results

        seen: set[str] = set()
        for hit in hits:
            if len(results) >= limit:
                break
            if not isinstance(hit, dict):
                continue
            key = _clean(hit.get("generated_internal_id")) or _clean(
                hit.get("Award ID")
            )
            if key and key in seen:
                continue
            built = self._build_result(hit, group, len(results) + 1)
            if built is None:
                continue
            if key:
                seen.add(key)
            results.append(built)
        return results

    @staticmethod
    def _request_body(query: str, codes: tuple[str, ...], limit: int) -> dict[str, Any]:
        """Build the JSON body of one award search request."""
        return {
            "filters": {"keywords": [query], "award_type_codes": list(codes)},
            "fields": list(_FIELDS),
            "page": 1,
            "limit": limit,
            "sort": _SORT_FIELD,
            "order": "desc",
            "subawards": False,
        }

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search federal awards matching *query*, ordered by awarded amount.

        A blank query performs no request.  The requested number of results is
        split between the contract and grant groups so both are represented,
        and ranks are assigned over the merged set.
        """
        cleaned = " ".join(query.split())
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        if limit <= 0:
            return ProviderResult(results=[])

        per_group = max(1, math.ceil(limit / len(_AWARD_TYPE_GROUPS)))
        results: list[SearchResult] = []
        async with self._client() as client:
            for group, codes in _AWARD_TYPE_GROUPS:
                group_limit = min(per_group, limit - len(results))
                if group_limit <= 0:
                    break
                resp = await client.post(
                    _SEARCH_URL,
                    json=self._request_body(cleaned, codes, group_limit),
                )
                resp.raise_for_status()
                results.extend(self._parse(resp.json(), group, group_limit))

        for rank, result in enumerate(results, start=1):
            result.rank = rank
        return ProviderResult(results=results)
