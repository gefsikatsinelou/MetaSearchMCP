"""Shodan InternetDB host intelligence for IP addresses.

InternetDB (internetdb.shodan.io) is a free, keyless Shodan endpoint that
answers a single question for one IP address::

    GET https://internetdb.shodan.io/{ip}

The reply lists the ports Shodan saw open on the host, the reverse-DNS
hostnames that resolve to it, the CPE identifiers of the software it runs,
free-form tags (for example ``cdn`` or ``vpn``) and the CVEs published for the
detected software.  A host that Shodan has never scanned answers ``404`` with
``{"detail": "No information available"}``.

Unlike :mod:`metasearchmcp.providers.nvd` and
:mod:`metasearchmcp.providers.cisa_kev`, which resolve a *vulnerability* to
the products it affects, this provider goes the other way around: given a
host it reports the exposure of that host (open ports, running software,
known CVEs), which is the usual starting point for an attack-surface or
exposure question.  The queries are real DNS-free lookups, so the query must
be an IP address; bare IPv4/IPv6 literals, bracketed IPv6 literals and URLs
such as ``https://8.8.8.8/status`` are all accepted.  No API key is required.
"""

from __future__ import annotations

import ipaddress
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://internetdb.shodan.io/{ip}"
_HOST_URL = "https://www.shodan.io/host/{ip}"


def normalize_ip(query: str) -> str | None:
    """Return the canonical IP address contained in *query*, else ``None``.

    Accepts what agents usually paste: a bare IP literal, a bracketed IPv6
    literal such as ``[2001:db8::1]``, an IPv4 literal with a port
    (``8.8.8.8:53``) or a full URL (``https://8.8.8.8/status``).  Anything
    that is not an IP address after that cleanup yields ``None``, so the
    provider never sends a request that InternetDB cannot answer.
    """
    candidate = query.strip()
    if not candidate:
        return None
    if "://" in candidate:
        candidate = candidate.split("://", 1)[1]
    candidate = candidate.split("/", 1)[0].strip()
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    # Strip a port suffix, but only for IPv4 literals: an IPv6 address is
    # built from colons, so it never has exactly one of them.
    if candidate.count(":") == 1:
        host, _, port = candidate.partition(":")
        if port.isdigit():
            candidate = host
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _int_list(value: object) -> list[int]:
    """Coerce a JSON value to a sorted list of unique integers."""
    if not isinstance(value, list):
        return []
    ports: set[int] = set()
    for item in value:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            ports.add(item)
        elif isinstance(item, str) and item.strip().isdigit():
            ports.add(int(item.strip()))
    return sorted(ports)


def _str_list(value: object) -> list[str]:
    """Coerce a JSON value to a list of non-empty, whitespace-normalized strings."""
    if not isinstance(value, list):
        return []
    items: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = " ".join(item.split())
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            items.append(cleaned)
    return items


def _is_private(ip: str) -> bool:
    """Return True when *ip* is a private, loopback or otherwise reserved range."""
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


class InternetDbProvider(BaseProvider):
    """Look up Shodan InternetDB exposure data for a single IP address.

    Keyless.  Each result is one host and carries its open ports, reverse-DNS
    hostnames, CPE identifiers, Shodan tags and the CVEs published for the
    software it runs.
    """

    name = "internetdb"
    description = (
        "Look up Shodan InternetDB host intelligence for an IP address: open "
        "ports, reverse-DNS hostnames, CPEs, tags and known CVEs, with no API "
        "key required."
    )
    tags: ClassVar[list[str]] = ["security", "network", "web"]

    @staticmethod
    def _snippet(
        ports: list[int],
        hostnames: list[str],
        cpes: list[str],
        tags: list[str],
        vulns: list[str],
    ) -> str:
        """Compose the snippet describing one host's exposure."""
        parts: list[str] = []
        if ports:
            parts.append(f"Open ports ({len(ports)}): {', '.join(map(str, ports))}")
        if hostnames:
            parts.append(f"Hostnames: {', '.join(hostnames)}")
        if tags:
            parts.append(f"Tags: {', '.join(tags)}")
        if cpes:
            parts.append(f"CPEs: {', '.join(cpes)}")
        if vulns:
            parts.append(f"Known CVEs ({len(vulns)}): {', '.join(vulns)}")
        if not parts:
            parts.append(
                "No open ports, hostnames, tags or known CVEs recorded for this host.",
            )
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(self, data: dict[str, Any], ip: str) -> SearchResult:
        """Build the single :class:`SearchResult` for *ip* from InternetDB data."""
        ports = _int_list(data.get("ports"))
        hostnames = _str_list(data.get("hostnames"))
        cpes = _str_list(data.get("cpes"))
        tags = _str_list(data.get("tags"))
        vulns = _str_list(data.get("vulns"))

        return SearchResult(
            title=f"Shodan InternetDB: {ip}",
            url=_HOST_URL.format(ip=ip),
            snippet=self._snippet(ports, hostnames, cpes, tags, vulns),
            source="shodan.io",
            rank=1,
            provider=self.name,
            extra={
                "ip": ip,
                "ports": ports,
                "port_count": len(ports),
                "hostnames": hostnames,
                "cpes": cpes,
                "tags": tags,
                "vulns": vulns,
                "vuln_count": len(vulns),
                "has_known_vulnerabilities": bool(vulns),
                "is_private": _is_private(ip),
            },
        )

    def _parse(self, data: object, ip: str) -> ProviderResult:
        """Parse an InternetDB payload for *ip* into structured results."""
        if not isinstance(data, dict):
            return ProviderResult(results=[])
        return ProviderResult(results=[self._build_result(data, ip)])

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Look up InternetDB exposure data for the IP address in *query*.

        Queries that do not contain an IP address, and hosts that Shodan has
        never scanned, return an empty result set instead of an error.
        """
        ip = normalize_ip(query)
        if ip is None:
            return ProviderResult(results=[])

        async with self._client() as client:
            resp = await client.get(_API_URL.format(ip=ip))
            # Shodan answers 404 for hosts it has no record of.
            if resp.status_code == 404:
                return ProviderResult(results=[])
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, ip)
