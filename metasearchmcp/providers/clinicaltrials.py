"""ClinicalTrials.gov clinical trial search via the public v2 API.

ClinicalTrials.gov (U.S. National Library of Medicine) is the largest
registry of clinical studies worldwide. Its read-only v2 JSON API
requires no API key:

``GET https://clinicaltrials.gov/api/v2/studies?query.term=QUERY&pageSize=N&format=json``

Each study exposes the NCT id, official/brief title, recruitment
status, sponsor, conditions, study type, and (when present) the
primary completion date. The provider is keyless and uses only the
shared httpx client from the base provider.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://clinicaltrials.gov/api/v2/studies"
_MAX_API_RESULTS = 25
# Recruiting / active studies are more actionable than completed ones;
# show them first when the API returns them mixed with other statuses.
_ACTIVE_STATUSES = {"RECRUITING", "ACTIVE_NOT_RECRUITING", "NOT_YET_RECRUITING"}


class ClinicalTrialsProvider(BaseProvider):
    """Search registered clinical trials via the keyless ClinicalTrials.gov v2 API.

    Each hit carries the NCT identifier, title, recruitment status,
    sponsor, conditions, study type, and primary completion date
    (when known). Actively recruiting studies are ranked first.
    """

    name = "clinicaltrials"
    description = (
        "Search registered clinical trials (NCT studies) via ClinicalTrials.gov, "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "web", "medical", "bio"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search ClinicalTrials.gov for *query* and return study results."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        request_params = {
            "query.term": query,
            "format": "json",
            "pageSize": limit,
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=request_params)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, max_results=limit)

    @staticmethod
    def _recruitment_rank(status: str) -> int:
        """Rank a recruitment status so active studies sort before others.

        Active statuses (recruiting, active not recruiting, not yet
        recruiting) get rank 0; everything else gets rank 1, keeping a
        stable secondary order for equal ranks.
        """
        return 0 if status in _ACTIVE_STATUSES else 1

    @staticmethod
    def _date_or_empty(value: Any) -> str:
        """Return a *value*'s date portion (YYYY-MM or YYYY-MM-DD) as text.

        The v2 API reports dates as objects like ``{"date": "2026-04", ...}``
        or plain strings; ``None``/missing values yield an empty string.
        """
        if isinstance(value, dict):
            value = value.get("date") or ""
        return str(value or "").strip()

    def _parse(
        self,
        data: dict[str, Any],
        max_results: int | None = None,
    ) -> ProviderResult:
        """Parse the ClinicalTrials.gov v2 JSON response into structured results."""
        results: list[SearchResult] = []
        limit = max_results or self._max_results
        studies = data.get("studies") or []

        for item in studies:
            if not isinstance(item, dict):
                continue
            protocol = item.get("protocolSection") or {}
            identification = protocol.get("identificationModule") or {}
            status_module = protocol.get("statusModule") or {}
            design = protocol.get("designModule") or {}

            title = (identification.get("briefTitle") or "").strip()
            nct_id = (identification.get("nctId") or "").strip()
            if not title or not nct_id:
                continue

            status = (status_module.get("overallStatus") or "").strip()
            conditions = [
                str(condition).strip()
                for condition in (protocol.get("conditionsModule") or {}).get(
                    "conditions",
                )
                or []
                if str(condition).strip()
            ]
            sponsor = (
                (protocol.get("sponsorCollaboratorsModule") or {})
                .get("leadSponsor", {})
                .get("name")
                or ""
            ).strip()
            study_type = (design.get("studyType") or "").strip()
            completion_date = self._date_or_empty(
                status_module.get("completionDateStruct"),
            )

            snippet_parts: list[str] = []
            if status:
                snippet_parts.append(f"Status: {status}")
            if conditions:
                snippet_parts.append(f"Conditions: {', '.join(conditions[:4])}")
            if sponsor:
                snippet_parts.append(f"Sponsor: {sponsor}")
            if study_type:
                snippet_parts.append(f"Type: {study_type}")

            results.append(
                SearchResult(
                    title=title,
                    url=f"https://clinicaltrials.gov/study/{nct_id}",
                    snippet=" | ".join(snippet_parts),
                    source="clinicaltrials.gov",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=completion_date or None,
                    extra={
                        "nct_id": nct_id,
                        "overall_status": status,
                        "conditions": conditions,
                        "sponsor": sponsor,
                        "study_type": study_type,
                        "primary_completion_date": completion_date,
                    },
                ),
            )
            if len(results) >= limit:
                break

        # Active/recruiting studies are more useful to surface first.
        results.sort(
            key=lambda r: (
                self._recruitment_rank(r.extra.get("overall_status", "")),
                r.rank,
            ),
        )
        for idx, hit in enumerate(results, start=1):
            hit.rank = idx

        return ProviderResult(results=results)
