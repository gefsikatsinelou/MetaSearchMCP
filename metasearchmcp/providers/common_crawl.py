"""Common Crawl index lookup (URL inventory and capture history).

The Common Crawl Foundation publishes monthly web crawls and keeps a keyless
columnar index of every capture.  The index answers two different questions:

* *Does this crawl contain this address, and how often?* — one record per
  capture, with the WARC file that stores the page body::

      GET https://index.commoncrawl.org/CC-MAIN-2026-39-index?url=example.com

* *Which pages of this site did the crawl see?* — the same endpoint with
  ``matchType=domain`` (host and subdomains) or ``matchType=prefix`` (URLs
  starting with the given path) enumerates crawled URLs, which is the usual way
  to discover a site's pages, or a host's subdomains, from a public crawl.

Responses are newline-delimited JSON, one object per capture::

    {"url": "https://example.com/", "timestamp": "20260904132130",
     "status": "200", "mime": "text/html", "digest": "KFMR3RACAHZZH2HGKDPO...",
     "length": "954", "offset": "185952529", "languages": "eng",
     "filename": "crawl-data/CC-MAIN-2026-39/segments/.../CC-...warc.gz"}

``https://data.commoncrawl.org/<filename>`` is the WARC holding the record, and
``<filename>`` plus ``offset``/``length`` locate the page body inside it.  The
index name (``CC-MAIN-YYYY-WW``) doubles as the crawl identifier, so results can
be pinned to one crawl with a trailing token, e.g. ``example.com CC-MAIN-2024-10``;
without one, the newest published crawl is used.  No API key is required.

Unlike :mod:`metasearchmcp.providers.wayback`, which reports how the Internet
Archive captured a page over time, this provider reports what the Common Crawl
web crawls contain, and hands back the raw WARC coordinates for the page body.
"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar, NamedTuple

import httpx

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_COLLINFO_URL = "https://index.commoncrawl.org/collinfo.json"
_INDEX_URL = "https://index.commoncrawl.org/{index}-index"
_DATA_URL = "https://data.commoncrawl.org/{filename}"

# Number of index records requested per wanted result.  A URL usually has
# several captures per crawl, so asking for exactly *limit* records would
# fill the reply with repeats of one address.
_RECORDS_PER_URL = 10
# Hard cap on index records fetched in a single request, to keep the lookup
# fast and to stay well inside the index server's scan budget.
_MAX_API_RECORDS = 1000
# A crawl index can be busy and answer 5xx while the range scan warms up, so a
# single retry noticeably improves the success rate of domain/prefix queries.
_ATTEMPTS = 2

# Crawl identifier, e.g. ``CC-MAIN-2026-39``.
_INDEX_RE = re.compile(r"CC-MAIN-\d{4}-\d{2}", re.IGNORECASE)
# RFC 1035 hostname label; the TLD is alphabetic or a punycode ``xn--`` label.
_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_TLD_RE = re.compile(r"(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})")

# Status codes that describe a page worth reporting by name; anything else is
# listed as-is in the ``statuses`` extra field.
_OK_STATUS = "200"


class QueryPlan(NamedTuple):
    """What to ask the index for: the address, the crawl and the match mode."""

    target: str
    crawl: str | None
    match_type: str


def extract_index(query: str) -> tuple[str, str | None]:
    """Split a trailing crawl identifier off *query*.

    ``"example.com CC-MAIN-2024-10"`` becomes
    ``("example.com", "CC-MAIN-2024-10")`` so the lookup can be pinned to that
    crawl instead of the newest one.
    """
    head, _, tail = query.strip().rpartition(" ")
    if head and _INDEX_RE.fullmatch(tail.strip()):
        return head.strip(), tail.strip().upper()
    return query.strip(), None


def normalize_target(query: str) -> str | None:
    """Return the web address contained in *query*, else ``None``.

    Accepts what agents usually paste: a bare host (``example.com``), a full URL
    (``https://example.com/login?next=1``) or a host with a port
    (``example.com:8080/a``).  Scheme, credentials and fragment are dropped,
    because the index matches on host, path and query.  Anything that names no
    web address — a phrase, a bare label, an IP literal — yields ``None``, so
    the provider never asks the index for something it cannot answer.
    """
    candidate = query.strip()
    if not candidate or len(candidate) > 2000:
        return None
    if any(char.isspace() for char in candidate):
        return None
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


def parse_query(query: str) -> QueryPlan | None:
    """Turn a user query into the index request it implies.

    A bare host asks about the whole site (``matchType=domain``); an address
    with a path or query string asks about that URL and everything below it
    (``matchType=prefix``).  ``None`` means the query names no address.
    """
    address_query, crawl = extract_index(query)
    target = normalize_target(address_query)
    if target is None:
        return None
    match_type = "domain" if "/" not in target else "prefix"
    return QueryPlan(target=target, crawl=crawl, match_type=match_type)


def _latest_index(payload: object) -> str | None:
    """Return the newest crawl identifier from a ``collinfo.json`` payload.

    Entries are compared on their ``to`` date — the newest crawl is the one that
    ends last — so the choice does not depend on the order the server lists
    collinfo entries in.
    """
    if not isinstance(payload, list):
        return None
    candidates: list[tuple[str, str]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        index_id = entry.get("id")
        if not isinstance(index_id, str) or not index_id.strip():
            continue
        to_date = entry.get("to")
        candidates.append(
            (to_date if isinstance(to_date, str) else "", index_id.strip())
        )
    if not candidates:
        return None
    return max(candidates)[1]


def parse_records(body: str) -> list[dict[str, Any]]:
    """Parse newline-delimited JSON records, skipping anything malformed."""
    records: list[dict[str, Any]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _text(value: object) -> str | None:
    """Return *value* as a non-empty stripped string, else ``None``."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _byte_count(value: object) -> int | None:
    """Return *value* as a non-negative byte count, else ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _human_size(value: int | None) -> str | None:
    """Format a byte count for humans (``954 B``, ``1.2 kB``, ``3.4 MB``)."""
    if value is None:
        return None
    if value < 1000:
        return f"{value} B"
    if value < 1_000_000:
        return f"{value / 1000:.1f} kB"
    return f"{value / 1_000_000:.1f} MB"


def _iso_date(stamp: str) -> str | None:
    """Convert a 14-digit capture stamp to an ISO ``YYYY-MM-DD`` date."""
    if len(stamp) >= 8 and stamp[:8].isdigit():
        return f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}"
    return None


class CommonCrawlProvider(BaseProvider):
    """Look up what the Common Crawl web crawls contain for an address.

    Keyless.  Each result covers one crawled URL: how many times the crawls
    captured it, the first and latest capture dates, the observed HTTP statuses,
    MIME types and languages, how many distinct content versions were seen, and
    the WARC file and byte range holding the page body.
    """

    name = "common_crawl"
    description = (
        "Query the Common Crawl open web index (monthly crawls of billions of "
        "pages): for a URL, domain or path prefix it reports which crawled URLs "
        "exist, how often each was captured, first and latest capture dates, "
        "HTTP statuses, MIME types, languages, the number of distinct content "
        "versions, and the WARC file plus byte range that stores each page "
        "body. Accepts 'example.com', 'https://example.com/login' and an "
        "optional trailing crawl such as 'example.com CC-MAIN-2024-10'. Useful "
        "for URL/subdomain discovery, checking whether a page is in a public "
        "crawl, and retrieving raw crawl records. No API key required."
    )
    tags: ClassVar[list[str]] = ["web", "archive", "data", "history"]

    @staticmethod
    def _record_summary(record: dict[str, Any]) -> dict[str, Any]:
        """Extract the fields a single index record contributes to a result."""
        return {
            "timestamp": _text(record.get("timestamp")) or "",
            "status": _text(record.get("status")),
            "mime": _text(record.get("mime")) or _text(record.get("mime-detected")),
            "digest": _text(record.get("digest")),
            "languages": _text(record.get("languages")),
            "length": _byte_count(record.get("length")),
            "filename": _text(record.get("filename")),
            "offset": _byte_count(record.get("offset")),
        }

    def _aggregate(
        self,
        records: list[dict[str, Any]],
        *,
        index: str,
        plan: QueryPlan,
        limit: int,
    ) -> list[SearchResult]:
        """Group index records by URL and build one result per crawled URL.

        Results are ranked by latest capture date, because the freshest crawl
        record of a URL is what a search usually needs; ties are broken by
        capture count and then by address, so the order is stable.
        """
        groups: dict[str, dict[str, Any]] = {}
        for record in records:
            url = _text(record.get("url"))
            if url is None:
                continue
            summary = self._record_summary(record)
            group = groups.get(url)
            if group is None:
                group = {
                    "captures": 0,
                    "first": summary["timestamp"],
                    "latest": None,
                    "statuses": set(),
                    "mimes": set(),
                    "languages": set(),
                    "digests": set(),
                }
                groups[url] = group
            group["captures"] += 1
            if summary["timestamp"] and (
                not group["first"] or summary["timestamp"] < group["first"]
            ):
                group["first"] = summary["timestamp"]
            if group["latest"] is None or (
                summary["timestamp"] > group["latest"]["timestamp"]
            ):
                group["latest"] = summary
            if summary["status"]:
                group["statuses"].add(summary["status"])
            if summary["mime"]:
                group["mimes"].add(summary["mime"])
            if summary["languages"]:
                group["languages"].add(summary["languages"])
            if summary["digest"]:
                group["digests"].add(summary["digest"])

        ordered = sorted(
            groups.items(),
            key=lambda item: (
                item[1]["latest"]["timestamp"] if item[1]["latest"] else "",
                item[1]["captures"],
                item[0],
            ),
            reverse=True,
        )
        results = [
            self._build_result(url, group, index=index, plan=plan)
            for url, group in ordered[:limit]
        ]
        for rank, result in enumerate(results, start=1):
            result.rank = rank
        return results

    def _build_result(
        self,
        url: str,
        group: dict[str, Any],
        *,
        index: str,
        plan: QueryPlan,
    ) -> SearchResult:
        """Build the :class:`SearchResult` for one crawled URL."""
        captures = group["captures"]
        latest = group["latest"] or {}
        first_stamp = group["first"] or None
        latest_stamp = latest.get("timestamp") or None
        first_date = _iso_date(first_stamp) if first_stamp else None
        latest_date = _iso_date(latest_stamp) if latest_stamp else None
        statuses = sorted(group["statuses"])
        mimes = sorted(group["mimes"])
        languages = sorted(group["languages"])
        versions = len(group["digests"])
        size = _human_size(latest.get("length"))

        parts: list[str] = [
            f"{captures} capture{'' if captures == 1 else 's'} in {index}"
        ]
        # Dates and statuses come before the longer category lists so the most
        # useful context survives when a snippet is truncated.
        if latest_date:
            suffix = f" (status {latest['status']})" if latest.get("status") else ""
            parts.append(f"Latest: {latest_date}{suffix}")
        if first_date and first_date != latest_date:
            parts.append(f"First: {first_date}")
        if statuses and statuses != [_OK_STATUS]:
            parts.append(f"Statuses: {', '.join(statuses)}")
        if mimes:
            parts.append(f"Types: {', '.join(mimes[:3])}")
        if languages:
            parts.append(f"Languages: {', '.join(languages[:3])}")
        if versions > 1:
            parts.append(f"Content versions: {versions}")
        if size:
            parts.append(f"Latest size: {size}")

        filename = latest.get("filename")
        offset = latest.get("offset")
        length = latest.get("length")
        query = {
            "url": plan.target,
            "output": "json",
            "matchType": plan.match_type,
        }

        return SearchResult(
            title=url,
            url=url,
            snippet=" | ".join(parts)[:MAX_SNIPPET_LENGTH],
            source="index.commoncrawl.org",
            provider=self.name,
            extra={
                "target": plan.target,
                "match_type": plan.match_type,
                "index": index,
                "crawl": index,
                "captures": captures,
                "first_capture": first_stamp,
                "first_capture_date": first_date,
                "latest_capture": latest_stamp,
                "latest_capture_date": latest_date,
                "statuses": statuses,
                "mime_types": mimes,
                "languages": languages,
                "content_versions": versions,
                "latest_digest": latest.get("digest"),
                "latest_length": length,
                "warc_filename": filename,
                "warc_offset": offset,
                "warc_length": length,
                "warc_url": _DATA_URL.format(filename=filename) if filename else None,
                "index_url": _INDEX_URL.format(index=index),
                "cdx_query_url": str(
                    httpx.URL(_INDEX_URL.format(index=index), params=query)
                ),
            },
        )

    async def _request(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """GET *url*, retrying once on a transport error or a 5xx response.

        The index server answers 5xx while a heavy range scan warms up, so one
        retry turns a noticeable share of failures into results.  Client errors
        are returned as-is for the caller to interpret (the index uses 404 for
        "no captures" and for an unknown crawl).
        """
        last_error: Exception | None = None
        last_server_error: httpx.Response | None = None
        for _ in range(_ATTEMPTS):
            try:
                resp = await client.get(url, params=params)
            except httpx.TransportError as exc:  # timeouts, connection resets
                last_error = exc
                continue
            if resp.status_code < 500:
                return resp
            last_server_error = resp
        if last_server_error is not None:
            last_server_error.raise_for_status()
        assert last_error is not None
        raise last_error

    async def _resolve_index(self, client: httpx.AsyncClient) -> str | None:
        """Return the newest published crawl identifier, else ``None``."""
        resp = await self._request(client, _COLLINFO_URL)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        try:
            payload = resp.json()
        except (json.JSONDecodeError, ValueError):
            return None
        return _latest_index(payload)

    async def _query_records(
        self,
        client: httpx.AsyncClient,
        index: str,
        plan: QueryPlan,
        limit: int,
    ) -> str | None:
        """Return the raw NDJSON body for *plan*, or ``None`` when empty."""
        resp = await self._request(
            client,
            _INDEX_URL.format(index=index),
            params={
                "url": plan.target,
                "output": "json",
                "matchType": plan.match_type,
                "limit": min(max(limit, 1) * _RECORDS_PER_URL, _MAX_API_RECORDS),
            },
        )
        if resp.status_code == 404:  # "No Captures found for: ..."
            return None
        resp.raise_for_status()
        return resp.text.strip() or None

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Return the crawled URLs matching *query* in one Common Crawl crawl.

        Queries that name no web address, and addresses the crawl never saw,
        return an empty result set instead of an error.
        """
        plan = parse_query(query)
        if plan is None:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results)
        async with self._client() as client:
            index = plan.crawl or await self._resolve_index(client)
            if index is None:
                return ProviderResult(results=[])
            body = await self._query_records(client, index, plan, limit)

        if body is None:
            return ProviderResult(results=[])
        records = parse_records(body)
        if not records:
            return ProviderResult(results=[])
        return ProviderResult(
            results=self._aggregate(records, index=index, plan=plan, limit=limit)
        )
