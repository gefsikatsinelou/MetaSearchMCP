"""NSF award search via the keyless public awards API.

The U.S. National Science Foundation publishes every award it makes through
the public Research.gov awards API.  It indexes research grants, continuing
grants, cooperative agreements, fellowships, conferences and research
infrastructure projects funded across the NSF directorates -- mathematical and
physical sciences, geosciences, engineering, computer and information science,
biological sciences, social and economic sciences, education and the
NSF-wide programmes.

Each record carries the award's title and abstract, its NSF award id, the
awardee organisation and its location, the principal investigators and
co-principal investigators, the funding programme, directorate and division,
the award's start and end dates, the obligated and estimated-total amounts,
the award type, the Catalog of Federal Domestic Assistance (CFDA) number and
the cognizant programme officer.

The endpoint is public and keyless and takes the query as a URL parameter::

    GET https://api.nsf.gov/services/v1/awards.json?keyword=QUERY&rpp=N

``keyword`` is matched against award titles, abstracts and the awardee and
programme metadata, so a multi-word query behaves as a conjunction over those
fields.  The response is::

    {"response": {"award": [...],
                  "metadata": {"offset": 0, "rpp": N, "totalCount": N}}}

ordered by the API's relevance ranking; a query without matches comes back
with an empty ``award`` list.  The API reports queries it cannot parse (for
example one containing square brackets) with HTTP 200 and a
``serviceNotification`` marked ``FATAL`` rather than with an error status, and
those are reported here as an empty result set.

This complements the other funding sources: Grants.gov covers the funding
opportunities agencies publish, NIH RePORTER covers NIH awards, and this
provider covers the award record the NSF itself maintains.  No API key is
required.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar
from urllib.parse import quote_plus

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.nsf.gov/services/v1/awards.json"
# Detail page of a single award, keyed by the API's award id.
_AWARD_PAGE_URL = "https://www.nsf.gov/awardsearch/show-award/?AWD_ID="
# Fallback award search used for hits the API returns without an id.
_SEARCH_URL = "https://www.nsf.gov/awardsearch/search-results/?QueryText={query}"
_SOURCE = "nsf.gov"
# The API behaves well with pages of this size; keep them small for agents.
_MAX_API_RESULTS = 50
# Characters of the award abstract copied into the snippet.
_SNIPPET_ABSTRACT_LENGTH = 180
# Characters of the funding-programme listing kept in the snippet.  The API
# packs every programme an award counts under into one comma-separated string,
# which would otherwise crowd out the abstract.
_SNIPPET_PROGRAM_LENGTH = 80
# Investigators listed in a snippet before closing with "et al.".
_SNIPPET_PI_LIMIT = 3
# Fiscal-year obligation entries kept in ``extra``.
_MAX_FUNDS_ENTRIES = 10

# The API puts the contact e-mail of every investigator in the same string as
# the name; it is dropped so snippets stay readable.
_EMAIL = re.compile(r"\S+@\S+")
# Award dates arrive as ``MM/DD/YYYY``.
_US_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
# Dates already in ``YYYY-MM-DD`` form are passed through.
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _people(value: object) -> list[str]:
    """Return the investigator names of a ``pi``/``coPDPI`` listing.

    Every entry pairs a name with the investigator's e-mail address, which is
    stripped; duplicates keep their first position.
    """
    if isinstance(value, str):
        entries: list[object] = [value]
    elif isinstance(value, (list, tuple)):
        entries = list(value)
    else:
        return []

    names: list[str] = []
    for entry in entries:
        text = " ".join(_EMAIL.sub(" ", _clean(entry)).split())
        text = text.strip(" ,;")
        if text and text not in names:
            names.append(text)
    return names


def _iso_date(value: object) -> str | None:
    """Return an ``MM/DD/YYYY`` award date as ``YYYY-MM-DD``.

    ``None`` is returned for empty, unparseable or out-of-range dates.
    """
    text = _clean(value)
    if not text:
        return None

    match = _US_DATE.match(text)
    if match:
        month, day, year = (int(part) for part in match.groups())
        if not 1 <= month <= 12 or not 1 <= day <= 31:
            return None
        return f"{year:04d}-{month:02d}-{day:02d}"

    # Already ISO formatted (optionally with a time suffix).
    iso = _ISO_DATE.match(text)
    return iso.group(0) if iso else None


def _amount(value: object) -> int | None:
    """Return a numeric award amount, ignoring booleans and junk values."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("$", "")
        try:
            return int(float(text))
        except ValueError:
            return None
    return None


def _money(value: object) -> str:
    """Format an award amount as e.g. ``$494,304``; blank when not numeric."""
    amount = _amount(value)
    return f"${amount:,}" if amount is not None else ""


def _truncate(value: str, limit: int) -> str:
    """Shorten *value* to *limit* characters, appending an ellipsis."""
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _funds(value: object) -> list[str]:
    """Return the per-fiscal-year obligations of an award, newest last."""
    if not isinstance(value, (list, tuple)):
        return []
    entries: list[str] = []
    for entry in value:
        text = _clean(entry)
        if text and text not in entries:
            entries.append(text)
            if len(entries) >= _MAX_FUNDS_ENTRIES:
                break
    return entries


class NsfAwardsProvider(BaseProvider):
    """Search NSF awards for funded research projects.

    Keyless.  *query* is matched against award titles, abstracts and the
    awardee and programme metadata in a single request, and the API's
    relevance order is preserved.  Each result carries the award id, title,
    abstract excerpt, principal investigators, awardee organisation and
    location, funding programme, directorate and division, start/end dates,
    obligated and estimated-total amounts, award type and CFDA number, and
    links to the award page on nsf.gov.
    """

    name = "nsf_awards"
    description = (
        "Search NSF awards — U.S. National Science Foundation funded research "
        "(award id, title, abstract, principal investigators, awardee "
        "organisation, programme, directorate and division, start/end dates, "
        "obligated and estimated-total amounts, award type) via the keyless "
        "awards API."
    )
    tags: ClassVar[list[str]] = ["academic", "gov", "science", "funding"]

    @staticmethod
    def _award_url(hit: dict[str, Any]) -> str:
        """Return the award page URL of a hit.

        Awards are keyed by their NSF award id; a hit without one falls back
        to a site search for its title so a link is always returned.
        """
        award_id = _clean(hit.get("id"))
        if award_id:
            return f"{_AWARD_PAGE_URL}{award_id}"
        return _SEARCH_URL.format(query=quote_plus(_clean(hit.get("title"))))

    @staticmethod
    def _period(start: str | None, end: str | None) -> str:
        """Join the award's start and end dates into a project period."""
        return " to ".join(part for part in (start, end) if part)

    @staticmethod
    def _location(hit: dict[str, Any]) -> str:
        """Return the awardee location as ``City, ST`` / ``City, Country``."""
        city = _clean(hit.get("awardeeCity"))
        region = _clean(hit.get("awardeeStateCode")) or _clean(
            hit.get("awardeeCountryCode")
        )
        return ", ".join(part for part in (city, region) if part)

    @staticmethod
    def _active(value: object) -> bool | None:
        """Return the ``activeAwd`` flag as a boolean when it is present."""
        text = _clean(value).lower()
        if text in {"true", "false"}:
            return text == "true"
        return None

    def _snippet(
        self,
        pis: list[str],
        awardee: str,
        location: str,
        program: str,
        division: str,
        amount: str,
        period: str,
        award_type: str,
        abstract: str,
    ) -> str:
        """Compose the snippet for a single award.

        Investigators come first, followed by the awardee and a metadata tail
        of programme, division, funding, project period and award type, and
        finally an excerpt of the abstract.
        """
        parts: list[str] = []
        if pis:
            listed = ", ".join(pis[:_SNIPPET_PI_LIMIT])
            if len(pis) > _SNIPPET_PI_LIMIT:
                listed += ", et al."
            parts.append(listed)
        if awardee:
            place = f"{awardee}, {location}" if location else awardee
            parts.append(f"Awardee: {place}")
        if program:
            parts.append(_truncate(program, _SNIPPET_PROGRAM_LENGTH))
        if division:
            parts.append(division)
        if amount:
            parts.append(f"Award: {amount}")
        if period:
            parts.append(f"Project period: {period}")
        if award_type:
            parts.append(award_type)
        if abstract:
            parts.append(f"Abstract: {abstract[:_SNIPPET_ABSTRACT_LENGTH]}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        hit: dict[str, Any],
        rank: int,
        total: int | None,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw NSF award record."""
        title = _clean(hit.get("title"))
        if not title:
            return None

        pis = _people(hit.get("pi"))
        co_pis = _people(hit.get("coPDPI"))
        awardee = _clean(hit.get("awardeeName")) or _clean(hit.get("awardee"))
        location = self._location(hit)
        program = _clean(hit.get("program")) or _clean(hit.get("fundProgramName"))
        directorate = _clean(hit.get("orgLongName"))
        division = _clean(hit.get("orgLongName2")) or _clean(hit.get("divAbbr"))
        award_type = _clean(hit.get("transType"))
        abstract = _clean(hit.get("abstractText"))
        start = _iso_date(hit.get("startDate"))
        end = _iso_date(hit.get("expDate"))
        obligated = _amount(hit.get("fundsObligatedAmt"))
        estimated = _amount(hit.get("estimatedTotalAmt"))
        award_id = _clean(hit.get("id"))

        return SearchResult(
            title=title,
            url=self._award_url(hit),
            snippet=self._snippet(
                pis,
                awardee,
                location,
                program,
                division,
                _money(obligated),
                self._period(start, end),
                award_type,
                abstract,
            ),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            published_date=start,
            extra={
                "award_id": award_id or None,
                "awardee": awardee or None,
                "awardee_location": location or None,
                "awardee_uei": _clean(hit.get("ueiNumber")) or None,
                "principal_investigators": pis,
                "co_principal_investigators": co_pis,
                "program": program or None,
                "directorate": directorate or None,
                "division": division or None,
                "funds_obligated": obligated,
                "estimated_total_amount": estimated,
                "funds_obligated_by_year": _funds(hit.get("fundsObligated")),
                "start_date": start,
                "end_date": end,
                "active": self._active(hit.get("activeAwd")),
                "award_type": award_type or None,
                "cfda_number": _clean(hit.get("cfdaNumber")) or None,
                "program_officer": _clean(hit.get("poName")) or None,
                "abstract": abstract or None,
                "total_results": total,
            },
        )

    @staticmethod
    def _total(data: dict[str, Any]) -> int | None:
        """Return the ``totalCount`` of a response's metadata block."""
        metadata = data.get("metadata")
        if not isinstance(metadata, dict):
            return None
        total = metadata.get("totalCount")
        if isinstance(total, bool) or not isinstance(total, int):
            return None
        return total

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse an NSF awards response into structured results.

        The API's relevance order is preserved and awards are deduplicated by
        their award id.  A ``serviceNotification`` response (as sent for
        requests the API cannot parse) and any other payload shape yield an
        empty result set.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        response = data.get("response")
        if not isinstance(response, dict):
            return ProviderResult(results=results)
        awards = response.get("award")
        if not isinstance(awards, list):
            return ProviderResult(results=results)

        max_results = self._max_results if limit is None else limit
        total = self._total(response)
        seen: set[str] = set()
        for hit in awards:
            if len(results) >= max_results:
                break
            if not isinstance(hit, dict):
                continue
            key = _clean(hit.get("id"))
            if key and key in seen:
                continue
            built = self._build_result(hit, len(results) + 1, total)
            if built is None:
                continue
            if key:
                seen.add(key)
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search NSF awards for the projects matching *query*.

        A blank query performs no request.  The API answers an unsatisfiable
        or unparseable search with an empty award list or a fatal
        ``serviceNotification``, both of which are reported as no results.
        """
        cleaned = " ".join(query.split())
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        if limit <= 0:
            return ProviderResult(results=[])

        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={"keyword": cleaned, "rpp": str(limit), "offset": "0"},
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
