"""NIH RePORTER funded-research-project search via the keyless public API.

NIH RePORTER (``reporter.nih.gov``) is the U.S. National Institutes of Health
database of funded extramural research: research project grants (R01, R21, ...),
career awards (K series), fellowships (F series), training grants (T32) and
SBIR/STTR awards.  Each record carries the funded project's title and abstract,
the principal investigators, the awarding institute or center, the fiscal-year
award amount, the performing organization and the project period.  The v2 API is
public and keyless; it is queried with a JSON ``POST`` request::

    POST https://api.reporter.nih.gov/v2/projects/search
    {
      "criteria": {"advanced_text_search": {
          "operator": "and", "search_field": "all", "search_text": QUERY}},
      "include_fields": [...], "offset": 0, "limit": N
    }

``search_field`` accepts ``All``, ``PROJECTTITLE``, ``TERMS`` or
``ABSTRACTTEXT``; ``all`` is used here so that project titles, abstracts and the
assigned project terms all contribute to a match, while ``operator`` ``and``
requires every query word to be present.  Matches come back ordered by
relevance, and a query without matches is answered with an empty ``results``
list, which this provider reports as an empty page rather than as a failure.

Records are large, so ``include_fields`` restricts the payload to the fields
rendered here.  Award amounts are per fiscal year, and repeat awards of the same
project appear as separate records, which are keyed by their application id.
This complements the literature, preprint and clinical-trial providers by
answering who is funding a research area, at which institution and for how much.
No API key is required.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.reporter.nih.gov/v2/projects/search"
# Landing page for a project; used when the API omits its own detail URL.
_PROJECT_URL = "https://reporter.nih.gov/project-details/"

# Fields requested from the API -- a full record is far larger than needed.
_INCLUDE_FIELDS: tuple[str, ...] = (
    "ApplId",
    "ProjectNum",
    "CoreProjectNum",
    "ProjectTitle",
    "AbstractText",
    "FiscalYear",
    "AwardAmount",
    "AgencyCode",
    "ActivityCode",
    "AgencyIcAdmin",
    "Organization",
    "PrincipalInvestigators",
    "ProjectStartDate",
    "ProjectEndDate",
    "OpportunityNumber",
    "AwardNoticeDate",
    "ProjectDetailUrl",
)
# Search titles, abstracts and the assigned project terms in one pass.
_SEARCH_FIELD = "all"
# The API pages its result lists; keep pages small for agents.
_MAX_API_RESULTS = 50
# Characters of the project abstract copied into the snippet.
_SNIPPET_ABSTRACT_LENGTH = 180
# Principal investigators listed in a snippet before closing with "et al.".
_SNIPPET_PI_LIMIT = 3


class NihReporterProvider(BaseProvider):
    """Search NIH RePORTER for funded research projects.

    Keyless.  Queries the RePORTER v2 search API in a single request and returns
    one hit per funded project (application), carrying the project number,
    title, abstract excerpt, principal investigators, funding institute,
    fiscal-year award amount, performing organization and project period, and
    linking to the project page on reporter.nih.gov.
    """

    name = "nih_reporter"
    description = (
        "Search NIH RePORTER — U.S. federally funded research projects "
        "(grants: title, abstract, principal investigators, funding "
        "institute, award amount, organization, project period) via the "
        "keyless v2 API."
    )
    tags: ClassVar[list[str]] = ["academic", "medical", "gov", "funding"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @classmethod
    def _date(cls, value: object) -> str:
        """Return the ``YYYY-MM-DD`` prefix of an ISO datetime, else ``""``."""
        if not isinstance(value, str):
            return ""
        return value[:10]

    @classmethod
    def _pis(cls, item: dict[str, Any]) -> list[str]:
        """Return the principal investigator names of a project."""
        names: list[str] = []
        for entry in item.get("principal_investigators") or []:
            if not isinstance(entry, dict):
                continue
            name = cls._clean(entry.get("full_name"))
            if name:
                names.append(name)
        return names

    @classmethod
    def _organization(cls, item: dict[str, Any]) -> tuple[str, str]:
        """Return the ``(name, location)`` of the performing organization.

        The location is the state for U.S. organizations, otherwise the
        organization's city.
        """
        organization = item.get("organization")
        if not isinstance(organization, dict):
            return "", ""
        name = cls._clean(organization.get("org_name"))
        location = cls._clean(
            organization.get("org_state") or organization.get("org_city")
        )
        return name, location

    @classmethod
    def _agency(cls, item: dict[str, Any]) -> tuple[str, str]:
        """Return the ``(abbreviation, name)`` of the awarding institute."""
        admin = item.get("agency_ic_admin")
        if not isinstance(admin, dict):
            return "", ""
        return cls._clean(admin.get("abbreviation")), cls._clean(admin.get("name"))

    @staticmethod
    def _award(value: object) -> str:
        """Format a fiscal-year award amount as e.g. ``$692,210``."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return ""
        return f"${int(value):,}"

    def _snippet(
        self,
        pis: list[str],
        fiscal_year: str,
        agency: str,
        activity_code: str,
        award: str,
        organization: str,
        location: str,
        period: str,
        abstract: str,
    ) -> str:
        """Compose the snippet for a single project."""
        parts: list[str] = []
        if pis:
            listed = ", ".join(pis[:_SNIPPET_PI_LIMIT])
            if len(pis) > _SNIPPET_PI_LIMIT:
                listed += ", et al."
            parts.append(listed)
        if fiscal_year:
            parts.append(f"FY {fiscal_year}")
        if agency or activity_code:
            parts.append(" ".join(bit for bit in (agency, activity_code) if bit))
        if award:
            parts.append(f"Award: {award}")
        if organization:
            place = f"{organization}, {location}" if location else organization
            parts.append(f"Organization: {place}")
        if period:
            parts.append(f"Project period: {period}")
        if abstract:
            parts.append(f"Abstract: {abstract[:_SNIPPET_ABSTRACT_LENGTH]}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(self, item: dict[str, Any]) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw RePORTER project."""
        title = self._clean(item.get("project_title"))
        if not title:
            return None

        pis = self._pis(item)
        organization, location = self._organization(item)
        agency, agency_name = self._agency(item)
        agency_code = self._clean(item.get("agency_code"))
        activity_code = self._clean(item.get("activity_code"))
        raw_year = item.get("fiscal_year")
        fiscal_year = str(raw_year) if isinstance(raw_year, int) else ""
        raw_award = item.get("award_amount")
        abstract = self._clean(item.get("abstract_text"))
        start = self._date(item.get("project_start_date"))
        end = self._date(item.get("project_end_date"))
        period = " to ".join(bit for bit in (start, end) if bit)
        appl_id = item.get("appl_id")
        project_id = appl_id if isinstance(appl_id, int) else None

        url = self._clean(item.get("project_detail_url"))
        if not url and project_id is not None:
            url = f"{_PROJECT_URL}{project_id}"

        return SearchResult(
            title=title,
            url=url,
            snippet=self._snippet(
                pis,
                fiscal_year,
                agency or agency_code,
                activity_code,
                self._award(raw_award),
                organization,
                location,
                period,
                abstract,
            ),
            source="reporter.nih.gov",
            provider=self.name,
            published_date=start or None,
            extra={
                "appl_id": project_id,
                "project_num": self._clean(item.get("project_num")) or None,
                "core_project_num": self._clean(item.get("core_project_num")) or None,
                "fiscal_year": raw_year if isinstance(raw_year, int) else None,
                "award_amount": (
                    raw_award
                    if isinstance(raw_award, (int, float))
                    and not isinstance(raw_award, bool)
                    else None
                ),
                "agency": agency or agency_code or None,
                "agency_name": agency_name or None,
                "activity_code": activity_code or None,
                "organization": organization or None,
                "organization_location": location or None,
                "principal_investigators": pis,
                "project_start_date": start or None,
                "project_end_date": end or None,
                "opportunity_number": self._clean(item.get("opportunity_number"))
                or None,
                "award_notice_date": self._date(item.get("award_notice_date")) or None,
                "abstract": abstract or None,
            },
        )

    def _parse(self, data: object, limit: int) -> list[SearchResult]:
        """Parse a RePORTER response, deduplicating hits by application id."""
        if not isinstance(data, dict):
            return []
        items = data.get("results")
        if not isinstance(items, list):
            return []

        results: list[SearchResult] = []
        seen: set[object] = set()
        for item in items:
            if len(results) >= limit:
                break
            if not isinstance(item, dict):
                continue
            # A project is keyed by its application id.
            key = item.get("appl_id")
            if key is not None:
                if key in seen:
                    continue
                seen.add(key)
            result = self._build_result(item)
            if result is None:
                continue
            results.append(result)

        # The API already ranks by relevance; keep that order and number it.
        for rank, result in enumerate(results, start=1):
            result.rank = rank
        return results

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search NIH RePORTER for funded projects matching *query*.

        Every query word must occur in the project title, its abstract or its
        assigned project terms.  A blank query performs no request.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {
            "criteria": {
                "advanced_text_search": {
                    "operator": "and",
                    "search_field": _SEARCH_FIELD,
                    "search_text": cleaned,
                },
            },
            "include_fields": list(_INCLUDE_FIELDS),
            "offset": 0,
            "limit": limit,
        }

        async with self._client() as client:
            resp = await client.post(_API_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()

        return ProviderResult(results=self._parse(data, limit))
