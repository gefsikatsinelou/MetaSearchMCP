"""Wayback Machine capture-history lookup.

The Internet Archive's Wayback Machine has been capturing snapshots of public
web pages since 1996, so "was this page archived, when, and how often" is a
single keyless request to its capture-profile endpoint::

    GET https://web.archive.org/__wb/sparkline?output=json&url=example.com

The reply is JSON.  ``first_ts`` and ``last_ts`` are the 14-digit stamps of the
earliest and latest capture, and ``years`` maps each calendar year to twelve
monthly capture counts, so a page's archival footprint is visible at a glance::

    {"years": {"2002": [1, 0, 1, 0, 3, 2, 1, 25, 14, 0, 4, 0], ...},
     "first_ts": "20020120142510", "last_ts": "20260926020229"}

``https://web.archive.org/web/<year>/<url>`` then replays the capture closest to
that year, and ``https://web.archive.org/web/<stamp>/<url>`` replays an exact
capture.  Unlike :mod:`metasearchmcp.providers.internet_archive`, which searches
archived item *metadata* (texts, audio, video, software), this provider reports
how a single web address has been captured over time — the usual way to check
whether a dead link has an archived copy, to see when a page changed or
disappeared, or to replay an archived version.  No API key is required.
"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SPARKLINE_URL = "https://web.archive.org/__wb/sparkline"
_REPLAY_URL = "https://web.archive.org/web/{stamp}/{original}"
_MAX_API_RESULTS = 50

_MONTH_NAMES = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

# The Wayback Machine began capturing in 1996; anything earlier is not a
# capture year and is more likely to be part of the address itself.
_MIN_YEAR = 1996
_MAX_YEAR = 2100

# Wayback replay URLs embed the original address after the capture stamp.
_REPLAY_PREFIX_RE = re.compile(
    r"^(?:https?://)?web\.archive\.org/web/\d+[a-z_]*/",
    re.IGNORECASE,
)

# RFC 1035 hostname label; the TLD is alphabetic or a punycode ``xn--`` label.
_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_TLD_RE = re.compile(r"(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})")


def extract_year(query: str) -> tuple[str, int | None]:
    """Split a trailing capture year off *query*.

    ``"example.com 2015"`` becomes ``("example.com", 2015)`` so the lookup can
    be restricted to that year.  A trailing token that is not a plausible
    capture year stays in place, because it may be part of the address.
    """
    stripped = query.strip()
    head, _, tail = stripped.rpartition(" ")
    if not (head and len(tail) == 4 and tail.isdigit()):
        return stripped, None
    year = int(tail)
    if _MIN_YEAR <= year <= _MAX_YEAR:
        return head.strip(), year
    return stripped, None


def normalize_target(query: str) -> str | None:
    """Return the web address contained in *query*, else ``None``.

    Accepts what agents usually paste: a bare host (``example.com``), a full
    URL (``https://example.com/login?next=1``), a host with a port
    (``example.com:8080/a``) or a Wayback replay URL, which is reduced to the
    address it replays.  The scheme, credentials and fragment are dropped,
    because the Wayback Machine matches on host and path.  Anything that names
    no web address — a phrase, a bare label, an IP literal — yields ``None``,
    so the provider never asks the archive for something it cannot answer.
    """
    candidate = query.strip()
    if not candidate or len(candidate) > 2000:
        return None
    if any(char.isspace() for char in candidate):
        return None
    candidate = _REPLAY_PREFIX_RE.sub("", candidate)
    if "://" in candidate:
        candidate = candidate.split("://", 1)[1]
    candidate = candidate.split("#", 1)[0]
    host, separator, rest = candidate.partition("/")
    # Drop credentials; a host has at most one colon (IPv6 literals are
    # rejected below, as they are not hostnames).
    host = host.rsplit("@", 1)[-1]
    if host.count(":") == 1:
        host = host.split(":", 1)[0]
    host = host.strip(".").removeprefix("*.").removeprefix("%.").lower()
    if not host:
        return None
    labels = host.split(".")
    if len(labels) < 2:
        return None
    if not all(_LABEL_RE.fullmatch(label) for label in labels[:-1]):
        return None
    if not _TLD_RE.fullmatch(labels[-1]):
        return None
    return f"{host}/{rest}" if separator and rest else host


def _count(value: object) -> int:
    """Return *value* as a non-negative capture count, else ``0``."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0
    return max(int(value), 0)


def _capture_stamp(value: object) -> str | None:
    """Return a 14-digit capture stamp, else ``None``."""
    if isinstance(value, str) and len(value) >= 14 and value[:14].isdigit():
        return value[:14]
    return None


def _iso_date(stamp: str | None) -> str | None:
    """Convert a 14-digit capture stamp to an ISO ``YYYY-MM-DD`` date."""
    if stamp is None:
        return None
    return f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}"


def _year_counts(payload: object) -> list[tuple[int, list[int]]]:
    """Return ``(year, monthly capture counts)`` for years that have captures.

    Years come back newest first, because a page's recent history is what a
    search usually needs.  A payload that is not the expected mapping — or a
    year whose counts are all zero — contributes nothing.
    """
    if not isinstance(payload, dict):
        return []
    years = payload.get("years")
    if not isinstance(years, dict):
        return []
    counts: list[tuple[int, list[int]]] = []
    for key, value in years.items():
        if not isinstance(key, str) or len(key) != 4 or not key.isdigit():
            continue
        if not isinstance(value, list):
            continue
        months = [_count(month) for month in value[:12]]
        months.extend([0] * (12 - len(months)))
        if not any(months):
            continue
        counts.append((int(key), months))
    return sorted(counts, key=lambda item: item[0], reverse=True)


class WaybackProvider(BaseProvider):
    """Look up how the Internet Archive Wayback Machine captured a web address.

    Keyless.  Each result covers one archived year: the number of captures, the
    months inside it that were captured and a link that replays the archived
    version closest to that year.
    """

    name = "wayback"
    description = (
        "Check how the Internet Archive Wayback Machine captured a web page: "
        "for a URL or domain, the years it was archived in with per-year "
        "capture counts and the months inside each year, the earliest and "
        "latest capture dates, and links that replay the archived versions. "
        "Useful to tell whether a dead link has an archived copy, when a page "
        "changed or disappeared, or how a page looked in a given year. Accepts "
        "'example.com', 'https://example.com/login' and an optional trailing "
        "year, e.g. 'example.com 2015'. No API key required."
    )
    tags: ClassVar[list[str]] = ["web", "archive", "history", "knowledge"]

    def _build_result(
        self,
        year: int,
        months: list[int],
        payload: dict[str, Any],
        target: str,
        total: int,
    ) -> SearchResult:
        """Build the :class:`SearchResult` for one archived year."""
        captures = sum(months)
        first_stamp = _capture_stamp(payload.get("first_ts"))
        last_stamp = _capture_stamp(payload.get("last_ts"))
        first_date = _iso_date(first_stamp)
        last_date = _iso_date(last_stamp)
        replay = _REPLAY_URL.format(stamp=year, original=target)
        busy_months = ", ".join(
            f"{_MONTH_NAMES[index]} {count}"
            for index, count in enumerate(months)
            if count
        )

        parts: list[str] = [
            f"{captures} capture{'' if captures == 1 else 's'} in {year}"
        ]
        # The overall range is stated before the per-month breakdown so the most
        # useful context survives when a busy year pushes the snippet over its
        # length limit.
        if first_date and last_date:
            parts.append(f"Archived range: {first_date} to {last_date}")
        if busy_months:
            parts.append(f"Months: {busy_months}")

        return SearchResult(
            title=f"Wayback captures of {target} in {year}",
            url=replay,
            snippet=" | ".join(parts)[:MAX_SNIPPET_LENGTH],
            source="web.archive.org",
            provider=self.name,
            extra={
                "target": target,
                "year": year,
                "captures": captures,
                "months": months,
                "total_captures": total,
                "first_capture": first_stamp,
                "last_capture": last_stamp,
                "first_capture_date": first_date,
                "last_capture_date": last_date,
                "replay_url": replay,
                "latest_snapshot_url": (
                    _REPLAY_URL.format(stamp=last_stamp, original=target)
                    if last_stamp
                    else None
                ),
            },
        )

    def _parse(
        self,
        payload: object,
        target: str,
        *,
        year: int | None = None,
        limit: int = _MAX_API_RESULTS,
    ) -> ProviderResult:
        """Parse a capture-profile payload into one result per archived year."""
        all_counts = _year_counts(payload)
        total = sum(sum(months) for _, months in all_counts)
        profile = payload if isinstance(payload, dict) else {}
        selected = [
            (year_, months)
            for year_, months in all_counts
            if year is None or year_ == year
        ][:limit]
        results = [
            self._build_result(year_, months, profile, target, total)
            for year_, months in selected
        ]
        for rank, result in enumerate(results, start=1):
            result.rank = rank
        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Return the capture history of the address named by *query*.

        Queries that name no web address, and addresses the archive never
        captured, return an empty result set instead of an error.
        """
        target_query, year = extract_year(query)
        target = normalize_target(target_query)
        if target is None:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _SPARKLINE_URL,
                params={"output": "json", "url": target, "collection": "web"},
            )
            resp.raise_for_status()
            body = resp.text.strip()

        if not body:
            return ProviderResult(results=[])
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return ProviderResult(results=[])

        return self._parse(payload, target, year=year, limit=limit)
