"""Search ProPublica's Nonprofit Explorer register of U.S. tax-exempt organizations.

ProPublica's Nonprofit Explorer (``projects.propublica.org/nonprofits``) indexes
the IRS Exempt Organizations Business Master File — every organization that
holds, or has applied for, tax-exempt status in the United States — and serves it
through a public, keyless JSON API::

    GET https://projects.propublica.org/nonprofits/api/v2/search.json?q=QUERY

The endpoint takes free-text keywords (an organization name, a city, or a
taxpayer EIN), matches them against organization names, and answers with the
total number of matches plus a single page of at most 25 ``organization``
records.  Each record carries the employer identification number (both as the
integer ``ein`` and as the formatted ``strein``), the legal name, a secondary
name, the city and state, the NTEE classification code, and the IRS subsection
under which the organization is exempt.

This complements the U.S. government and legal providers (Federal Register,
Grants.gov, CourtListener) with a searchable register of non-profit
organizations, each linking to its ProPublica profile and IRS Form 990 filing
history.  No API key or registration is required.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://projects.propublica.org/nonprofits/api/v2/search.json"
# Public profile page of a single organization, keyed by its EIN.
_ORGANIZATION_URL = "https://projects.propublica.org/nonprofits/organizations/"
# Nonprofit Explorer home page, used when a record carries no usable EIN.
_HOME_URL = "https://projects.propublica.org/nonprofits/"
# The search endpoint paginates at a fixed 25 organizations per request.
_MAX_API_RESULTS = 25
# Characters of an organization's secondary name kept in a snippet.
_SNIPPET_SUBNAME_LENGTH = 120

# NTEE major group letters mapped to the category they stand for (NTEE-CC).
_NTEE_MAJOR_GROUPS: dict[str, str] = {
    "A": "Arts, Culture & Humanities",
    "B": "Education",
    "C": "Environment",
    "D": "Animal-Related",
    "E": "Health Care",
    "F": "Mental Health & Crisis Intervention",
    "G": "Disease, Disorders & Medical Disciplines",
    "H": "Medical Research",
    "I": "Crime & Legal-Related",
    "J": "Employment",
    "K": "Food, Agriculture & Nutrition",
    "L": "Housing & Shelter",
    "M": "Public Safety, Disaster Preparedness & Relief",
    "N": "Recreation & Sports",
    "O": "Youth Development",
    "P": "Human Services",
    "Q": "International, Foreign Affairs & National Security",
    "R": "Civil Rights, Social Action & Advocacy",
    "S": "Community Improvement & Capacity Building",
    "T": "Philanthropy, Voluntarism & Grantmaking Foundations",
    "U": "Science & Technology",
    "V": "Social Science",
    "W": "Public & Societal Benefit",
    "X": "Religion-Related",
    "Y": "Mutual & Membership Benefit",
    "Z": "Unknown",
}


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _string(value: object) -> str:
    """Return a plain string field, or an empty string."""
    return value if isinstance(value, str) else ""


def _int(value: object) -> int | None:
    """Return an integer field, ignoring booleans and non-integer values."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _float(value: object) -> float | None:
    """Return a numeric relevance score, ignoring booleans and junk."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _subsection_label(code: int | None) -> str | None:
    """Return the IRS subsection label for a Nonprofit Explorer subsection code.

    The API reuses ``subseccd`` for both section 501(c) subsections (1-29) and
    the special code 92, which stands for a 4947(a)(1) split-interest trust.
    """
    if code is None:
        return None
    if code == 92:
        return "4947(a)(1)"
    if 1 <= code <= 29:
        return f"501(c)({code})"
    return None


class ProPublicaNonprofitsProvider(BaseProvider):
    """Search ProPublica's Nonprofit Explorer register of U.S. nonprofits.

    Keyless.  Queries the Nonprofit Explorer search API in a single request and
    returns one hit per matching organization, carrying its EIN, legal and
    secondary names, location, NTEE category, IRS subsection and relevance
    score, and linking to the organization's ProPublica profile page.
    """

    name = "propublica_nonprofits"
    description = (
        "Search ProPublica's Nonprofit Explorer — the IRS register of U.S. "
        "tax-exempt organizations — by name, city or EIN, returning each "
        "nonprofit's EIN, location, NTEE category, IRS subsection (501(c)(3), "
        "...) and a link to its Form 990 filing history. No API key required."
    )
    tags: ClassVar[list[str]] = ["reference", "nonprofit", "us"]

    @staticmethod
    def _ein(item: dict[str, Any]) -> str:
        """Return an organization's EIN as a digit string, or an empty string.

        ``strein`` is preferred because it preserves any leading zeros that the
        integer ``ein`` field drops; the integer is used as a fallback.
        """
        formatted = _string(item.get("strein")).replace("-", "").strip()
        if formatted.isdigit():
            return formatted
        number = _int(item.get("ein"))
        return str(number) if number is not None else ""

    @staticmethod
    def _name(item: dict[str, Any]) -> str:
        """Return an organization's display name (legal name, else sub name)."""
        return _clean(item.get("name")) or _clean(item.get("sub_name"))

    @staticmethod
    def _ntee(item: dict[str, Any]) -> tuple[str, str | None]:
        """Return the NTEE classification code and its major-group category."""
        code = _clean(item.get("ntee_code")) or _clean(item.get("raw_ntee_code"))
        if not code:
            return "", None
        return code, _NTEE_MAJOR_GROUPS.get(code[0].upper())

    @staticmethod
    def _snippet(
        location: str,
        sub_name: str,
        ntee_code: str,
        ntee_category: str | None,
        subsection: str | None,
        display_ein: str,
    ) -> str:
        """Compose the snippet for a single organization."""
        parts: list[str] = []
        if location:
            parts.append(f"Location: {location}")
        if sub_name:
            parts.append(f"Also known as: {sub_name[:_SNIPPET_SUBNAME_LENGTH]}")
        if ntee_code:
            label = f"{ntee_code} ({ntee_category})" if ntee_category else ntee_code
            parts.append(f"NTEE: {label}")
        if subsection:
            parts.append(f"IRS subsection: {subsection}")
        if display_ein:
            parts.append(f"EIN: {display_ein}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        total: int | None,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a Nonprofit Explorer record."""
        name = self._name(item)
        if not name:
            return None

        sub_name = _clean(item.get("sub_name"))
        if sub_name == name:
            sub_name = ""
        ein = self._ein(item)
        # Prefer the IRS-formatted "12-3456789" form when displaying an EIN.
        display_ein = _string(item.get("strein")).strip() or ein
        city = _clean(item.get("city"))
        state = _clean(item.get("state")).upper()
        location = ", ".join(part for part in (city, state) if part)
        ntee_code, ntee_category = self._ntee(item)
        subsection_code = _int(item.get("subseccd"))
        subsection = _subsection_label(subsection_code)
        url = f"{_ORGANIZATION_URL}{ein}" if ein else _HOME_URL

        return SearchResult(
            title=name,
            url=url,
            snippet=self._snippet(
                location,
                sub_name,
                ntee_code,
                ntee_category,
                subsection,
                display_ein,
            ),
            source="projects.propublica.org",
            rank=rank,
            provider=self.name,
            extra={
                "ein": ein or None,
                "strein": _string(item.get("strein")) or None,
                "name": name,
                "sub_name": sub_name or None,
                "city": city or None,
                "state": state or None,
                "ntee_code": ntee_code or None,
                "ntee_category": ntee_category,
                "subsection": subsection,
                "subsection_code": subsection_code,
                "score": _float(item.get("score")),
                "total_results": total,
                "url": url,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a Nonprofit Explorer search response into structured results.

        The endpoint answers with an object carrying an ``organizations`` array;
        any other shape yields an empty page.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        organizations = data.get("organizations")
        if not isinstance(organizations, list):
            return ProviderResult(results=results)

        total = _int(data.get("total_results"))
        max_results = limit or self._max_results
        for item in organizations:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            built = self._build_result(item, total, len(results) + 1)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Nonprofit Explorer for organizations matching *query*.

        A blank query performs no request.  The index's own relevance order is
        preserved in the returned results; the endpoint returns a single page of
        at most 25 organizations, so that is the effective page size.  Queries
        may be an organization name, a city, or a taxpayer EIN.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={"q": cleaned, "page": 0},
            )
            resp.raise_for_status()
            data: object = resp.json()

        return self._parse(data, limit)
