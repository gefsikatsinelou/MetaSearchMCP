"""NASA Exoplanet Archive confirmed-exoplanet search.

The NASA Exoplanet Archive (``exoplanetarchive.ipac.caltech.edu``) is NASA's
curated service for exoplanet data.  Its *Planetary Systems Composite
Parameters* table (``pscomppars``) holds one row per confirmed planet with the
best currently available value for every parameter, and it is queryable
through a public, keyless TAP (Table Access Protocol) endpoint::

    GET https://exoplanetarchive.ipac.caltech.edu/TAP/sync
        ?query=select ... from pscomppars where ... &format=json

The table has no free-text search field, so the query is matched against both
the planet name and the host-star name.  That makes a system name such as
``TRAPPIST-1`` return every planet in the system, while ``Kepler-16 b``
resolves to a single planet.  LIKE wildcards in the query are stripped before
the ADQL statement is built and single quotes are doubled, so a query cannot
widen or break its own match.

Each hit carries the host star, discovery year, method and facility, orbital
period, semi-major axis, radius, mass, equilibrium temperature, distance and
the number of stars/planets in the system, and links to the archive's planet
overview page.  No API key is required.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
# Landing page for a planet on the Exoplanet Archive front end.
_OVERVIEW_URL = "https://exoplanetarchive.ipac.caltech.edu/overview/"

# "Planetary Systems Composite Parameters": one row per confirmed planet.
_TABLE = "pscomppars"

# Columns requested for every hit; the archive rejects unknown identifiers.
_COLUMNS = (
    "pl_name",
    "hostname",
    "disc_year",
    "discoverymethod",
    "disc_facility",
    "pl_orbper",
    "pl_orbsmax",
    "pl_rade",
    "pl_bmasse",
    "pl_bmassprov",
    "pl_eqt",
    "sy_dist",
    # Number of stars and of known planets in the planetary system.
    "sy_snum",
    "sy_pnum",
)

# The TAP endpoint has no page-size parameter of its own: the row budget is
# fixed by the ADQL ``top`` clause, so oversampling happens there too.
_MAX_API_RESULTS = 60
_RANK_OVERSAMPLE = 3

# LIKE metacharacters are removed from the user query, so a query can never
# widen its own match (e.g. ``*`` or ``%`` matching the whole catalog).
_LIKE_METACHARACTERS = str.maketrans("", "", "%_")

_WORD_RE = re.compile(r"[a-z0-9]+")


class ExoplanetProvider(BaseProvider):
    """Search confirmed exoplanets in the NASA Exoplanet Archive.

    Keyless.  Queries the ``pscomppars`` table for planet- and host-star-name
    matches in a single TAP request, then re-ranks locally so exact and prefix
    matches lead the page.  Each hit carries the host star, discovery year,
    method and facility, orbital period, radius, mass, distance and
    equilibrium temperature, plus the size of the system.
    """

    name = "exoplanet"
    description = (
        "Search the NASA Exoplanet Archive confirmed-planet catalog by planet "
        "or host-star name — discovery year and method, orbital period, "
        "radius, mass, distance and equilibrium temperature — via the "
        "keyless TAP API."
    )
    tags: ClassVar[list[str]] = ["space", "science", "reference"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _number(value: object) -> float | None:
        """Return *value* as a float, ignoring booleans and non-numbers."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    @staticmethod
    def _int(value: object) -> int | None:
        """Return *value* as an int, ignoring booleans and non-numbers."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return int(value)

    @staticmethod
    def _measure(value: float | None, digits: int, unit: str) -> str:
        """Format a measurement as ``<number> <unit>`` (``""`` when missing).

        Trailing zeros are trimmed, so ``205.90`` renders as ``205.9`` and
        ``1134.0`` as ``1134``.  *digits* is always at least one, which keeps
        the zero-stripping from eating digits of the integer part.
        """
        if value is None:
            return ""
        return f"{value:.{digits}f}".rstrip("0").rstrip(".") + f" {unit}"

    @staticmethod
    def _labeled(pairs: list[tuple[str, str]]) -> list[str]:
        """Build ``"Label: value"`` parts, skipping empty values."""
        return [f"{label}: {value}" for label, value in pairs if value]

    @staticmethod
    def _discovery(year: int | None, method: str, facility: str) -> str:
        """Compose the discovery summary used in the snippet."""
        if not year and not method:
            return ""
        summary = f"Discovered {year}" if year else "Detected"
        if method:
            summary += f" via {method}"
        if facility:
            summary += f" ({facility})"
        return summary

    @staticmethod
    def _adql(term: str, top: int) -> str:
        """Return the ADQL statement used for a single search.

        Single quotes are doubled so *term* cannot terminate the SQL string
        literal; LIKE metacharacters are removed before the call.
        """
        literal = term.replace("'", "''")
        pattern = f"%{literal}%"
        return (
            f"select top {top} {', '.join(_COLUMNS)} from {_TABLE} "
            f"where (pl_name like '{pattern}' or hostname like '{pattern}') "
            "order by pl_name"
        )

    @classmethod
    def _score(
        cls,
        name: str,
        host: str,
        normalized: str,
        tokens: list[str],
    ) -> int:
        """Rank a hit by name match quality, then by token coverage.

        Exact name matches outrank prefixes, which in turn outrank host-star
        matches; token coverage breaks the remaining ties so ``Kepler-16 b``
        leads ``Kepler-160 b`` for the query ``kepler-16``.
        """
        lowered_name = name.casefold()
        lowered_host = host.casefold()

        score = 0
        if lowered_name == normalized:
            score += 100
        elif lowered_name.startswith(normalized):
            score += 20
        if lowered_host == normalized:
            score += 10
        elif lowered_host.startswith(normalized):
            score += 5
        score += 2 * sum(1 for token in tokens if token in lowered_host)
        score += sum(1 for token in tokens if token in lowered_name)
        return score

    def _build_result(self, item: dict[str, Any]) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw ``pscomppars`` row."""
        name = self._clean(item.get("pl_name"))
        if not name:
            return None

        host = self._clean(item.get("hostname"))
        year = self._int(item.get("disc_year"))
        method = self._clean(item.get("discoverymethod"))
        facility = self._clean(item.get("disc_facility"))
        period = self._number(item.get("pl_orbper"))
        axis = self._number(item.get("pl_orbsmax"))
        radius = self._number(item.get("pl_rade"))
        mass = self._number(item.get("pl_bmasse"))
        temp = self._number(item.get("pl_eqt"))
        distance = self._number(item.get("sy_dist"))
        stars = self._int(item.get("sy_snum"))
        planets = self._int(item.get("sy_pnum"))

        parts = [
            f"Host star {host}" if host else "",
            self._discovery(year, method, facility),
            f"{stars}-star system" if stars and stars > 1 else "",
            f"{planets} planets in system" if planets and planets > 1 else "",
            *self._labeled(
                [
                    ("Period", self._measure(period, 2, "d")),
                    ("Radius", self._measure(radius, 2, "Earth radii")),
                    ("Mass", self._measure(mass, 2, "Earth masses")),
                    ("Distance", self._measure(distance, 2, "pc")),
                    ("T_eq", self._measure(temp, 1, "K")),
                ]
            ),
        ]

        return SearchResult(
            title=name,
            url=f"{_OVERVIEW_URL}{quote(name, safe='')}",
            snippet=" | ".join(part for part in parts if part)[:MAX_SNIPPET_LENGTH],
            source="exoplanetarchive.ipac.caltech.edu",
            provider=self.name,
            extra={
                "planet": name,
                "host_star": host or None,
                "discovery_year": year,
                "discovery_method": method or None,
                "discovery_facility": facility or None,
                "stars_in_system": stars,
                "planets_in_system": planets,
                "orbital_period_days": period,
                "semi_major_axis_au": axis,
                "radius_earth": radius,
                "mass_earth": mass,
                "mass_provenance": self._clean(item.get("pl_bmassprov")) or None,
                "equilibrium_temp_k": temp,
                "distance_pc": distance,
            },
        )

    def _parse(
        self,
        data: object,
        normalized: str,
        tokens: list[str],
        oversample: int,
    ) -> list[SearchResult]:
        """Parse a TAP response, ranking the closest name matches first."""
        if not isinstance(data, list):
            return []

        scored: list[tuple[int, SearchResult]] = []
        for item in data:
            if len(scored) >= oversample:
                break
            if not isinstance(item, dict):
                continue
            result = self._build_result(item)
            if result is None:
                continue
            host = self._clean(item.get("hostname"))
            scored.append(
                (self._score(result.title, host, normalized, tokens), result),
            )

        # The sort is stable, so equally-relevant planets keep the archive's
        # alphabetical order (which groups a system's planets together).
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [result for _, result in scored]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the Exoplanet Archive for planets matching *query*.

        Planet and host-star names are matched in one table scan; exact and
        prefix matches are re-ranked to the top of the page.  A blank query —
        or one made up entirely of LIKE wildcards — performs no request.
        """
        cleaned = query.strip().translate(_LIKE_METACHARACTERS)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        oversample = min(limit * _RANK_OVERSAMPLE, _MAX_API_RESULTS)

        async with self._client() as client:
            resp = await client.get(
                _TAP_URL,
                params={"query": self._adql(cleaned, oversample), "format": "json"},
            )
            resp.raise_for_status()
            data = resp.json()

        normalized = cleaned.casefold()
        tokens = _WORD_RE.findall(normalized)
        results = self._parse(data, normalized, tokens, oversample)[:limit]
        for rank, result in enumerate(results, start=1):
            result.rank = rank
        return ProviderResult(results=results)
