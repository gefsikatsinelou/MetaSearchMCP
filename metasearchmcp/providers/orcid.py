"""ORCID researcher profile search via the public, keyless API.

ORCID (orcid.org) is a non-profit registry of unique identifiers for
researchers and scholars. Its public read-only API requires no API key and
returns JSON when the ``Accept: application/json`` header is sent:

``GET https://pub.orcid.org/v3.0/expanded-search/?q=QUERY&rows=N``

Each hit exposes the ORCID iD, the researcher's names, their affiliated
institution names, and any registered other names. Results link to the
public ORCID profile page. This complements the other academic providers by
answering *who* works on a topic rather than *what* was published.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://pub.orcid.org/v3.0/expanded-search"
_PROFILE_URL = "https://orcid.org/{orcid_id}"
# ORCID caps a single expanded-search request at this many rows.
_MAX_API_RESULTS = 1000


class OrcidProvider(BaseProvider):
    """Search researcher profiles registered with ORCID.

    Keyless. Uses the public expanded-search API; the ``Accept:
    application/json`` header is required to receive JSON instead of the
    default XML. Each result carries the researcher's ORCID iD, preferred
    name, and affiliated institution names, linked to the public profile
    page.
    """

    name = "orcid"
    description = (
        "Search researcher profiles registered with ORCID — the global "
        "researcher identifier registry — no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "web"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _string_list(value: object) -> list[str]:
        """Return a cleaned list of strings from an ORCID list field."""
        if not isinstance(value, list):
            return []
        return [
            OrcidProvider._clean_text(item)
            for item in value
            if OrcidProvider._clean_text(item)
        ]

    @staticmethod
    def _display_name(entry: dict[str, Any]) -> str:
        """Return the preferred display name for a researcher entry."""
        credit = OrcidProvider._clean_text(entry.get("credit-name"))
        if credit:
            return credit
        given = OrcidProvider._clean_text(entry.get("given-names"))
        family = OrcidProvider._clean_text(entry.get("family-names"))
        return " ".join(part for part in (given, family) if part)

    def _parse(
        self,
        data: dict[str, Any],
        max_results: int | None = None,
    ) -> ProviderResult:
        """Parse the ORCID expanded-search response into structured results."""
        results: list[SearchResult] = []
        limit = max_results or self._max_results
        entries = data.get("expanded-result") or []

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            orcid_id = self._clean_text(entry.get("orcid-id"))
            title = self._display_name(entry)
            if not orcid_id or not title:
                continue

            institutions = self._string_list(entry.get("institution-name"))
            other_names = self._string_list(entry.get("other-name"))

            snippet_parts: list[str] = []
            if institutions:
                snippet_parts.append(f"Affiliations: {', '.join(institutions[:5])}")
            if other_names:
                snippet_parts.append(f"Also known as: {', '.join(other_names[:5])}")

            results.append(
                SearchResult(
                    title=title,
                    url=_PROFILE_URL.format(orcid_id=orcid_id),
                    snippet=" | ".join(snippet_parts),
                    source="orcid.org",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "orcid_id": orcid_id,
                        "given_names": self._clean_text(entry.get("given-names")),
                        "family_names": self._clean_text(entry.get("family-names")),
                        "credit_name": self._clean_text(entry.get("credit-name")),
                        "institutions": institutions,
                        "other_names": other_names,
                    },
                ),
            )
            if len(results) >= limit:
                break

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search ORCID for researcher profiles matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {"q": query, "rows": str(limit)}
        headers = {"Accept": "application/json"}
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, max_results=limit)
