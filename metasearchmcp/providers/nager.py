"""Nager.Date public-holiday search via the keyless public API.

Nager.Date (date.nager.at) publishes public holidays for ~130 countries
from government and bank sources, updated yearly. Its v3 API needs no
API key:

``GET https://date.nager.at/api/v3/PublicHolidays/{year}/{countryCode}``
``GET https://date.nager.at/api/v3/NextPublicHolidays/{countryCode}``
``GET https://date.nager.at/api/v3/CountryInfo/{countryCode}``

Each hit carries the holiday name, local name, ISO date, the country code,
and metadata flags (``global``/regional-only, ``fixed`` date, and types
such as ``Public``/``Bank``). The provider is keyless, uses only the shared
httpx client, and tags itself ``reference``/``calendar``/``places`` so it
complements the existing Open-Meteo place-search provider for geography
queries (it is not a general web engine and therefore stays out of the
generic ``web`` pool).
"""

from __future__ import annotations

from datetime import date
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_CURRENT_YEAR = date.today().year

_API_BASE = "https://date.nager.at/api/v3"
# Nager.Date serves ISO 3166-1 alpha-2 country codes.
_VALID_CODES = {
    "AD",
    "AE",
    "AF",
    "AG",
    "AI",
    "AL",
    "AM",
    "AO",
    "AR",
    "AS",
    "AT",
    "AU",
    "AW",
    "AX",
    "AZ",
    "BA",
    "BB",
    "BD",
    "BE",
    "BF",
    "BG",
    "BH",
    "BI",
    "BJ",
    "BL",
    "BM",
    "BN",
    "BO",
    "BQ",
    "BR",
    "BS",
    "BT",
    "BV",
    "BW",
    "BY",
    "BZ",
    "CA",
    "CC",
    "CD",
    "CF",
    "CG",
    "CH",
    "CI",
    "CK",
    "CL",
    "CM",
    "CN",
    "CO",
    "CR",
    "CU",
    "CV",
    "CW",
    "CX",
    "CY",
    "CZ",
    "DE",
    "DJ",
    "DK",
    "DM",
    "DO",
    "DZ",
    "EC",
    "EE",
    "EG",
    "EH",
    "ER",
    "ES",
    "ET",
    "FI",
    "FJ",
    "FK",
    "FM",
    "FO",
    "FR",
    "GA",
    "GB",
    "GD",
    "GE",
    "GF",
    "GG",
    "GH",
    "GI",
    "GL",
    "GM",
    "GN",
    "GP",
    "GQ",
    "GR",
    "GS",
    "GT",
    "GU",
    "GW",
    "GY",
    "HK",
    "HM",
    "HN",
    "HR",
    "HT",
    "HU",
    "ID",
    "IE",
    "IL",
    "IM",
    "IN",
    "IO",
    "IQ",
    "IR",
    "IS",
    "IT",
    "JE",
    "JM",
    "JO",
    "JP",
    "KE",
    "KG",
    "KH",
    "KI",
    "KM",
    "KN",
    "KP",
    "KR",
    "KW",
    "KY",
    "KZ",
    "LA",
    "LB",
    "LC",
    "LI",
    "LK",
    "LR",
    "LS",
    "LT",
    "LU",
    "LV",
    "LY",
    "MA",
    "MC",
    "MD",
    "ME",
    "MF",
    "MG",
    "MH",
    "MK",
    "ML",
    "MM",
    "MN",
    "MO",
    "MP",
    "MQ",
    "MR",
    "MS",
    "MT",
    "MU",
    "MV",
    "MW",
    "MX",
    "MY",
    "MZ",
    "NA",
    "NC",
    "NE",
    "NF",
    "NG",
    "NI",
    "NL",
    "NO",
    "NP",
    "NR",
    "NU",
    "NZ",
    "OM",
    "PA",
    "PE",
    "PF",
    "PG",
    "PH",
    "PK",
    "PL",
    "PM",
    "PN",
    "PR",
    "PS",
    "PT",
    "PW",
    "PY",
    "QA",
    "RE",
    "RO",
    "RS",
    "RU",
    "RW",
    "SA",
    "SB",
    "SC",
    "SD",
    "SE",
    "SG",
    "SH",
    "SI",
    "SJ",
    "SK",
    "SL",
    "SM",
    "SN",
    "SO",
    "SR",
    "SS",
    "ST",
    "SV",
    "SX",
    "SY",
    "SZ",
    "TC",
    "TD",
    "TF",
    "TG",
    "TH",
    "TJ",
    "TK",
    "TL",
    "TM",
    "TN",
    "TO",
    "TR",
    "TT",
    "TV",
    "TW",
    "TZ",
    "UA",
    "UG",
    "UM",
    "US",
    "UY",
    "UZ",
    "VA",
    "VC",
    "VE",
    "VG",
    "VI",
    "VN",
    "VU",
    "WF",
    "WS",
    "YE",
    "YT",
    "ZA",
    "ZM",
    "ZW",
}

# Common English country names/aliases -> ISO code for friendly queries.
_COUNTRY_ALIASES: dict[str, str] = {
    "australia": "AU",
    "austria": "AT",
    "belgium": "BE",
    "brazil": "BR",
    "britain": "GB",
    "canada": "CA",
    "china": "CN",
    "czechia": "CZ",
    "czech republic": "CZ",
    "denmark": "DK",
    "england": "GB",
    "france": "FR",
    "germany": "DE",
    "great britain": "GB",
    "greece": "GR",
    "hong kong": "HK",
    "india": "IN",
    "ireland": "IE",
    "israel": "IL",
    "italy": "IT",
    "japan": "JP",
    "korea": "KR",
    "luxembourg": "LU",
    "mexico": "MX",
    "netherlands": "NL",
    "new zealand": "NZ",
    "norway": "NO",
    "poland": "PL",
    "portugal": "PT",
    "russia": "RU",
    "singapore": "SG",
    "south africa": "ZA",
    "south korea": "KR",
    "spain": "ES",
    "sweden": "SE",
    "switzerland": "CH",
    "turkey": "TR",
    "uk": "GB",
    "ukraine": "UA",
    "united kingdom": "GB",
    "united states": "US",
    "usa": "US",
    "us": "US",
}


class NagerDateProvider(BaseProvider):
    """Search public holidays of a country via Nager.Date.

    Keyless. The query is resolved to an ISO 3166-1 alpha-2 country code
    (``US``, ``DE``, ``japan``, ...); when it resolves, the country's
    public holidays for the requested year (default: the current year) are
    returned. Unknown codes fall back to the upcoming holidays of every
    supported country so a caller can still discover what is coming.
    """

    name = "nager"
    description = (
        "Search public holidays and observances by country — names, dates, "
        "and regional scope via the keyless Nager.Date API."
    )
    tags: ClassVar[list[str]] = ["reference", "calendar", "places"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    def _resolve(self, query: str) -> str:
        """Map *query* to an ISO 3166-1 alpha-2 country code, or ``\"\"``.

        A query that already looks like a two-letter ISO code is used
        verbatim (case-insensitive); otherwise the common English
        names/aliases table is consulted.
        """
        q = self._clean(query).lower()
        if not q:
            return ""
        if q in _COUNTRY_ALIASES:
            return _COUNTRY_ALIASES[q]
        if len(q) == 2 and q.isalpha():
            return q.upper()
        return ""

    @staticmethod
    def _holiday_url(date: str, country_code: str) -> str:
        """Build a human-facing Nager.Date URL for one holiday."""
        return f"https://date.nager.at/PublicHoliday/{country_code}/{date}"

    def _parse(
        self,
        data: Any,
        country_code: str,
        limit: int | None = None,
    ) -> ProviderResult:
        """Parse a PublicHolidays/NextPublicHolidays response into results."""
        results: list[SearchResult] = []
        if not isinstance(data, list):
            return ProviderResult(results=results)
        max_results = limit or self._max_results

        for item in data:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            name = self._clean(item.get("name"))
            date = self._clean(item.get("date"))
            if not name or not date:
                continue
            if len(date) >= 10:
                date_prefix = date[:10]
            else:
                date_prefix = date

            local_name = self._clean(item.get("localName"))
            country = self._clean(item.get("countryCode")) or country_code
            types = [
                str(t).strip() for t in (item.get("types") or []) if str(t).strip()
            ]
            flags = []
            if item.get("global") is True:
                flags.append("nationwide")
            if item.get("fixed") is True:
                flags.append("fixed date")
            scope = item.get("counties")
            if isinstance(scope, list) and scope:
                flags.append(f"{len(scope)} regions only")

            snippet_parts: list[str] = [country]
            if flags:
                snippet_parts.append(", ".join(flags))
            if types:
                snippet_parts.append(f"Type: {', '.join(types)}")
            if local_name and local_name != name:
                snippet_parts.append(f"Local: {local_name}")

            results.append(
                SearchResult(
                    title=f"{name} ({date_prefix})",
                    url=self._holiday_url(date_prefix, country),
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source="date.nager.at",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=date_prefix,
                    extra={
                        "country_code": country,
                        "local_name": local_name,
                        "date": date_prefix,
                        "global": bool(item.get("global")),
                        "fixed": bool(item.get("fixed")),
                        "types": types,
                        "counties": scope if isinstance(scope, list) else [],
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Nager.Date for holidays matching *query*.

        The query is resolved to a country code (``US``, ``DE``,
        ``japan``, ...). When it resolves, the country's public holidays
        for *year* (default: the current year) are returned; otherwise the
        upcoming holidays of every supported country are returned, which
        still lets a caller find what is coming next.
        """
        country_code = self._resolve(query)
        limit = min(params.num_results, self._max_results)

        async with self._client() as client:
            if country_code:
                # The country's public holidays for the current year.
                resp = await client.get(
                    f"{_API_BASE}/PublicHolidays/{_CURRENT_YEAR}/{country_code}",
                )
            else:
                # Unresolved query: show upcoming holidays worldwide so the
                # caller can still discover what is coming.
                resp = await client.get(f"{_API_BASE}/NextPublicHolidaysWorldwide")
            data = resp.json()

        return self._parse(data, country_code, limit)
