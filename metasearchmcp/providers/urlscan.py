"""urlscan.io public scan search.

urlscan.io loads a web page in a sandboxed browser, records every request the
page makes and publishes the result as a public *scan*.  Searching those scans
is a single keyless request::

    GET https://urlscan.io/api/v1/search/?q=<query>&size=<n>

The reply is JSON whose ``results`` list holds one object per scan: ``task``
(what was submitted, when and by which source), ``page`` (final URL, domain,
apex domain, resolved IP, ASN, country, server software, HTTP status, page
title and TLS issuer), ``stats`` (unique IPs, request count and transfer size),
any ``labels`` and the scan ``_id``.  That id addresses the human report page
``https://urlscan.io/result/<uuid>/``, the machine-readable report
``https://urlscan.io/api/v1/result/<uuid>/`` and the screenshot
``https://urlscan.io/screenshots/<uuid>.png``.

Unlike :mod:`metasearchmcp.providers.internetdb`, which reports what Shodan saw
open on an IP, and :mod:`metasearchmcp.providers.crtsh`, which lists the
certificates issued for a domain, this provider searches *observed page loads*:
which hosts resolve to an IP, what a suspicious domain served when it was last
scanned, which country and network a page was served from, or which scans
reference a file hash.  It is the usual way to check whether an unknown URL has
already been analysed, to pivot from an indicator (domain, IP, hash, ASN) to a
live page, or to find further samples of a campaign.

The search API needs no API key.  Anonymous callers only see public scans and
may not sort by a custom field or use regular expressions.  Host-shaped queries
are rewritten into the field syntax the API expects — ``example.com`` becomes
``page.domain:example.com``, ``8.8.8.8`` becomes ``ip:8.8.8.8`` and
``example.com/login`` becomes ``page.url:"example.com/login"`` — while queries
that already use urlscan search syntax (``page.country:RU``, ``hash:<sha256>``,
``task.tags:phishing``, ``domain:a.example OR domain:b.example``) are passed
through untouched.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://urlscan.io/api/v1/search/"
_RESULT_URL = "https://urlscan.io/result/{uuid}/"
_RESULT_API_URL = "https://urlscan.io/api/v1/result/{uuid}/"
_SCREENSHOT_URL = "https://urlscan.io/screenshots/{uuid}.png"

# The search API answers at most 100 scans per request.
_MAX_API_RESULTS = 100

# RFC 1035 hostname label; the TLD is alphabetic or a punycode ``xn--`` label.
_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_TLD_RE = re.compile(r"(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})")
# A URL path that can be put inside a quoted urlscan query without escaping.
_PATH_RE = re.compile(r"[^\s\"\\]*")


def parse_target(query: str) -> tuple[str, str] | None:
    """Return ``(host, path)`` for a host- or URL-shaped *query*, else ``None``.

    Accepts what agents usually paste: a bare host (``example.com``), a host
    with a port (``example.com:8080``), a full URL
    (``https://example.com/login?next=1``), a bracketed IPv6 URL or an IP
    literal.  The scheme, credentials and fragment are dropped, and a trailing
    port is removed, because urlscan matches scans on host and path.  Anything
    that does not name a single host — a phrase, a field query such as
    ``page.country:RU``, a bare word — yields ``None``, so it is left for the
    search API's own query language to interpret.
    """
    candidate = query.strip()
    if not candidate or any(char.isspace() for char in candidate):
        return None
    candidate = candidate.split("#", 1)[0]
    if "://" in candidate:
        candidate = candidate.split("://", 1)[1]
    host, _, path = candidate.lstrip("/").partition("/")
    # Drop credentials; a port is only stripped from ``host:8080``, because a
    # field query such as ``page.domain:example.com`` has a non-numeric tail.
    host = host.rsplit("@", 1)[-1].lstrip("/")
    if host.count(":") == 1:
        name, _, port = host.partition(":")
        if port.isdigit():
            host = name
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    host = host.strip(".").removeprefix("*.").removeprefix("%.").lower()
    if not host:
        return None
    if path and not _PATH_RE.fullmatch(path):
        return None
    if not host.isascii():
        # urlscan indexes the punycode form of internationalized domains.
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            return None
    try:
        return str(ipaddress.ip_address(host)), path
    except ValueError:
        pass
    labels = host.split(".")
    if len(labels) < 2:
        return None
    if not all(_LABEL_RE.fullmatch(label) for label in labels[:-1]):
        return None
    if not _TLD_RE.fullmatch(labels[-1]):
        return None
    return host, path


def build_search_query(query: str) -> str | None:
    """Return the urlscan search query for *query*, else ``None``.

    Host-shaped queries are rewritten into the field syntax the API expects, so
    that a bare domain searches the scans of that domain rather than the page
    text: ``example.com`` becomes ``page.domain:example.com`` (use
    ``domain:example.com`` explicitly to also match third-party requests made
    by those scans), ``8.8.8.8`` becomes ``ip:8.8.8.8`` and
    ``example.com/login`` becomes ``page.url:"example.com/login"``.  Every
    other non-empty query — free text or urlscan search syntax — is returned
    unchanged.  An empty query yields ``None``, so no request is made.
    """
    cleaned = query.strip()
    if not cleaned:
        return None
    target = parse_target(cleaned)
    if target is None:
        return cleaned
    host, path = target
    if path:
        return f'page.url:"{host}/{path}"'
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return f"page.domain:{host}"
    return f"ip:{host}"


def _mapping(value: object) -> dict[str, Any]:
    """Return *value* as a mapping, else an empty mapping."""
    return value if isinstance(value, dict) else {}


def _clean_text(value: object) -> str:
    """Return *value* as whitespace-normalized text, else ``""``."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _int_value(value: object) -> int | None:
    """Return *value* as an integer when it is a number or numeric string."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _str_list(value: object) -> list[str]:
    """Return *value* as a list of non-empty, deduplicated strings."""
    if not isinstance(value, list):
        return []
    items: list[str] = []
    seen: set[str] = set()
    for item in value:
        cleaned = _clean_text(item)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            items.append(cleaned)
    return items


class UrlscanProvider(BaseProvider):
    """Search public urlscan.io scans of web pages.

    Keyless.  Each result is one published scan and carries the scanned URL,
    its HTTP status, server software, IP, country, ASN, page title, HTTP
    transfer statistics, scan time and a link to the full report.
    """

    name = "urlscan"
    description = (
        "Search public urlscan.io scans of web pages: for a domain, URL, IP, "
        "ASN or file hash, the scans of that target with the scanned URL, HTTP "
        "status, server software, resolved IP, country, ASN, page title, "
        "transfer statistics, scan time and a link to the full report and "
        "screenshot. Useful to check whether an unknown URL has already been "
        "analysed, to see what a suspicious domain served, or to pivot from an "
        "indicator to related samples. Accepts 'example.com', "
        "'https://example.com/login', '8.8.8.8' or native urlscan syntax such "
        "as 'page.country:RU' and 'hash:<sha256>'. No API key required."
    )
    tags: ClassVar[list[str]] = ["security", "web", "network"]

    def _snippet(
        self,
        task: dict[str, Any],
        page: dict[str, Any],
        stats: dict[str, Any],
        labels: list[str],
    ) -> str:
        """Compose the snippet describing one scan."""
        parts: list[str] = []
        scan_time = _clean_text(task.get("time"))
        if scan_time:
            parts.append(f"Scanned {scan_time}")
        source = _clean_text(task.get("source")) or _clean_text(task.get("method"))
        if source:
            parts.append(f"Source: {source}")
        status = _clean_text(page.get("status"))
        mime = _clean_text(page.get("mimeType"))
        response = " ".join(
            part for part in (status and f"HTTP {status}", mime) if part
        )
        if response:
            parts.append(response)
        server = _clean_text(page.get("server"))
        if server:
            parts.append(f"Server: {server}")
        ip = _clean_text(page.get("ip"))
        country = _clean_text(page.get("country"))
        if ip:
            parts.append(f"IP {ip}" + (f" ({country})" if country else ""))
        asn = _clean_text(page.get("asn"))
        asn_name = _clean_text(page.get("asnname"))
        if asn or asn_name:
            parts.append(" ".join(part for part in (asn, asn_name) if part))
        requests = _int_value(stats.get("requests"))
        unique_ips = _int_value(stats.get("uniqIPs"))
        if requests is not None or unique_ips is not None:
            parts.append(f"{requests or 0} requests, {unique_ips or 0} unique IPs")
        if labels:
            parts.append(f"Labels: {', '.join(labels)}")
        tags = _str_list(task.get("tags"))
        if tags:
            parts.append(f"Tags: {', '.join(tags)}")
        if not parts:
            parts.append("Public urlscan.io scan of this page.")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(self, item: dict[str, Any]) -> SearchResult | None:
        """Build the :class:`SearchResult` for one scan, or ``None`` if unusable."""
        task = _mapping(item.get("task"))
        page = _mapping(item.get("page"))
        stats = _mapping(item.get("stats"))
        uuid = _clean_text(item.get("_id")) or _clean_text(task.get("uuid"))
        task_url = _clean_text(task.get("url")) or _clean_text(page.get("url"))
        if not task_url:
            return None
        title = _clean_text(page.get("title")) or task_url
        scan_time = _clean_text(task.get("time"))
        labels = _str_list(item.get("labels"))

        return SearchResult(
            title=title,
            url=_RESULT_URL.format(uuid=uuid) if uuid else task_url,
            snippet=self._snippet(task, page, stats, labels),
            source="urlscan.io",
            provider=self.name,
            published_date=self._iso_date_prefix(scan_time),
            extra={
                "uuid": uuid or None,
                "scan_url": _RESULT_URL.format(uuid=uuid) if uuid else None,
                "report_api_url": _RESULT_API_URL.format(uuid=uuid) if uuid else None,
                "screenshot_url": _SCREENSHOT_URL.format(uuid=uuid) if uuid else None,
                "task_url": task_url,
                "page_url": _clean_text(page.get("url")) or None,
                "domain": _clean_text(page.get("domain")) or None,
                "apex_domain": _clean_text(page.get("apexDomain")) or None,
                "ip": _clean_text(page.get("ip")) or None,
                "country": _clean_text(page.get("country")) or None,
                "server": _clean_text(page.get("server")) or None,
                "status": _clean_text(page.get("status")) or None,
                "mime_type": _clean_text(page.get("mimeType")) or None,
                "language": _clean_text(page.get("language")) or None,
                "asn": _clean_text(page.get("asn")) or None,
                "asn_name": _clean_text(page.get("asnname")) or None,
                "tls_issuer": _clean_text(page.get("tlsIssuer")) or None,
                "tls_valid_from": _clean_text(page.get("tlsValidFrom")) or None,
                "tls_age_days": _int_value(page.get("tlsAgeDays")),
                "tls_valid_days": _int_value(page.get("tlsValidDays")),
                "domain_age_days": _int_value(page.get("domainAgeDays")),
                "apex_domain_age_days": _int_value(page.get("apexDomainAgeDays")),
                "requests": _int_value(stats.get("requests")),
                "unique_ips": _int_value(stats.get("uniqIPs")),
                "unique_countries": _int_value(stats.get("uniqCountries")),
                "data_length": _int_value(stats.get("dataLength")),
                "labels": labels,
                "tags": _str_list(task.get("tags")),
                "source": _clean_text(task.get("source")) or None,
                "method": _clean_text(task.get("method")) or None,
                "visibility": _clean_text(task.get("visibility")) or None,
                "scan_time": scan_time or None,
            },
        )

    def _parse(self, payload: object, limit: int = _MAX_API_RESULTS) -> ProviderResult:
        """Parse a urlscan search response into one result per scan."""
        if not isinstance(payload, dict):
            return ProviderResult(results=[])
        raw = payload.get("results")
        if not isinstance(raw, list):
            return ProviderResult(results=[])
        results: list[SearchResult] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            result = self._build_result(item)
            if result is None:
                continue
            results.append(result)
            if len(results) >= limit:
                break
        for rank, result in enumerate(results, start=1):
            result.rank = rank
        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search public urlscan.io scans for *query*.

        An empty query returns an empty result set instead of a request.
        """
        search_query = build_search_query(query)
        if search_query is None:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={"q": search_query, "size": limit},
            )
            resp.raise_for_status()
            payload = resp.json()

        return self._parse(payload, limit)
