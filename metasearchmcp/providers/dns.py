"""DNS record lookup for domain names over DNS-over-HTTPS.

Cloudflare's public resolver speaks the JSON DNS API that Google standardised
for DNS-over-HTTPS, so a lookup is a single keyless request::

    GET https://cloudflare-dns.com/dns-query?name=example.com&type=MX
    Accept: application/dns-json

The reply carries a status code (``0`` NOERROR, ``3`` NXDOMAIN), the question
that was asked and an ``Answer`` array whose entries hold the owner name, the
numeric record type, the TTL in seconds and the record data itself.

Unlike :mod:`metasearchmcp.providers.rdap`, which reports who *registered* a
domain, this provider reports how the domain currently *resolves*: its address
records (``A``/``AAAA``), mail exchangers (``MX``), name servers (``NS``),
free-text records (``TXT``) and aliases (``CNAME``).  Any other record type the
resolver knows (``SOA``, ``CAA``, ``SRV``, ``HTTPS``, ...) can be requested
explicitly.  No API key is required.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://cloudflare-dns.com/dns-query"
_ACCEPT = "application/dns-json"

# Record types the resolver answers for, mapped to their numeric DNS codes.
_TYPE_CODES: dict[str, int] = {
    "A": 1,
    "NS": 2,
    "CNAME": 5,
    "SOA": 6,
    "PTR": 12,
    "MX": 15,
    "TXT": 16,
    "AAAA": 28,
    "SRV": 33,
    "DS": 43,
    "RRSIG": 46,
    "NSEC": 47,
    "DNSKEY": 48,
    "TLSA": 52,
    "SVCB": 64,
    "HTTPS": 65,
    "CAA": 257,
}

# Record types looked up when the query names a domain but no record type.
# These are the records agents ask for in practice; every other supported type
# is still available by naming it in the query.
_DEFAULT_TYPES: tuple[str, ...] = ("A", "AAAA", "MX", "NS", "TXT", "CNAME")

# RFC 1035 label; the TLD is either alphabetic or a punycode ``xn--`` label.
_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_TLD_RE = re.compile(r"(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})")


def normalize_domain(query: str) -> str | None:
    """Return the hostname contained in *query*, else ``None``.

    Accepts what agents usually paste: a bare hostname (``www.example.com``),
    a URL (``https://www.example.com/path?q=1``) or a host with a port
    (``example.com:443``).  Unlike the RDAP provider the ``www.`` prefix is
    kept, because ``www.example.com`` is a different DNS name from
    ``example.com`` and may well resolve to different records.  Anything that
    is not a plausible hostname after that cleanup — text with spaces, bare
    labels, IP addresses — yields ``None``, so the provider never sends a
    request the resolver cannot answer.
    """
    candidate = query.strip().lower()
    if not candidate or any(char.isspace() for char in candidate):
        return None
    if "://" in candidate:
        candidate = candidate.split("://", 1)[1]
    candidate = candidate.split("/", 1)[0]
    candidate = candidate.rsplit("@", 1)[-1]
    # Strip a port suffix; a hostname has at most one colon (IPv6 literals are
    # rejected below, as they are not domain names).
    if candidate.count(":") == 1:
        candidate = candidate.split(":", 1)[0]
    candidate = candidate.strip(".")
    if not candidate or len(candidate) > 253:
        return None
    labels = candidate.split(".")
    if len(labels) < 2:
        return None
    if not all(_LABEL_RE.fullmatch(label) for label in labels[:-1]):
        return None
    if not _TLD_RE.fullmatch(labels[-1]):
        return None
    return candidate


def parse_query(query: str) -> tuple[str, tuple[str, ...]] | None:
    """Split *query* into a hostname and the record types to look up.

    Record types may be written before or after the hostname and in any case
    (``example.com MX``, ``MX example.com``, ``mx example.com``).  When no
    record type is named the :data:`_DEFAULT_TYPES` set is used.  Queries with
    no hostname at all yield ``None``.
    """
    tokens = query.strip().split()
    if not tokens:
        return None

    requested: list[str] = []
    remaining: list[str] = []
    for token in tokens:
        candidate = token.strip(",;().").upper()
        if candidate in _TYPE_CODES:
            if candidate not in requested:
                requested.append(candidate)
        else:
            remaining.append(token)

    domain = normalize_domain(" ".join(remaining))
    if domain is None:
        return None
    return domain, tuple(requested) or _DEFAULT_TYPES


def _str(value: object) -> str | None:
    """Return a whitespace-normalized non-empty string, else ``None``."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _answers(payload: object, code: int) -> list[dict[str, Any]]:
    """Return the ``{name, ttl, data}`` answers of type *code* from *payload*.

    The resolver returns every record needed to answer the question (a
    ``CNAME`` chain, for example), so answers of other types are dropped.
    """
    if not isinstance(payload, dict):
        return []
    answers = payload.get("Answer")
    if not isinstance(answers, list):
        return []
    records: list[dict[str, Any]] = []
    for entry in answers:
        if not isinstance(entry, dict) or entry.get("type") != code:
            continue
        data = _str(entry.get("data"))
        if not data:
            continue
        ttl = entry.get("TTL")
        records.append(
            {
                "name": _str(entry.get("name")),
                "ttl": ttl if isinstance(ttl, int) else None,
                "data": data,
            }
        )
    return records


class DnsProvider(BaseProvider):
    """Resolve the DNS records of a domain name over DNS-over-HTTPS.

    Keyless.  Each result is one record type of one hostname and carries every
    answer of that type, the lowest TTL seen and whether the resolver
    authenticated the answer with DNSSEC.
    """

    name = "dns"
    description = (
        "Resolve a hostname's DNS records over DNS-over-HTTPS (Cloudflare): "
        "address records (A/AAAA), mail exchangers (MX), name servers (NS), "
        "text records (TXT), aliases (CNAME) and any other record type, with "
        "no API key required. Accepts 'example.com', 'example.com MX' or "
        "'MX example.com'."
    )
    tags: ClassVar[list[str]] = ["security", "network", "dns", "web"]

    @staticmethod
    def _snippet(record_type: str, records: list[dict[str, Any]]) -> str:
        """Compose the snippet listing every *record_type* answer found."""
        values = [str(record["data"]) for record in records]
        ttl = min(
            (record["ttl"] for record in records if record["ttl"] is not None),
            default=None,
        )
        snippet = f"{record_type}: {'; '.join(values)}"
        if ttl is not None:
            snippet = f"{snippet} | TTL: {ttl}s"
        return snippet[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        domain: str,
        record_type: str,
        records: list[dict[str, Any]],
        payload: dict[str, Any],
    ) -> SearchResult:
        """Build the :class:`SearchResult` for one record type of *domain*."""
        ttl = min(
            (record["ttl"] for record in records if record["ttl"] is not None),
            default=None,
        )
        owner = next(
            (record["name"] for record in records if record["name"]),
            domain,
        )
        query = f"name={domain}&type={record_type}"
        return SearchResult(
            title=f"DNS {record_type} records for {domain}",
            url=f"{_API_URL}?{query}",
            snippet=self._snippet(record_type, records),
            source="cloudflare-dns.com",
            provider=self.name,
            extra={
                "domain": domain,
                "record_type": record_type,
                "record_type_code": _TYPE_CODES[record_type],
                "record_count": len(records),
                "records": [record["data"] for record in records],
                "answers": records,
                "name": owner,
                "ttl": ttl,
                "status": payload.get("Status"),
                "dnssec_authenticated": payload.get("AD") is True,
            },
        )

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Resolve the DNS records requested by *query*.

        Every requested record type is looked up concurrently; types without
        answers are omitted, and a query that names no hostname (or a hostname
        that does not exist) returns an empty result set instead of an error.
        """
        parsed = parse_query(query)
        if parsed is None:
            return ProviderResult(results=[])
        domain, record_types = parsed
        limit = min(params.num_results, self._max_results)

        async def _fetch(record_type: str) -> tuple[str, object]:
            async with self._client() as client:
                resp = await client.get(
                    _API_URL,
                    params={"name": domain, "type": record_type},
                    headers={"Accept": _ACCEPT},
                )
                resp.raise_for_status()
                return record_type, resp.json()

        payloads = await asyncio.gather(
            *(_fetch(record_type) for record_type in record_types),
            return_exceptions=True,
        )
        failures = [payload for payload in payloads if isinstance(payload, Exception)]
        if len(failures) == len(payloads):
            raise failures[0]

        results: list[SearchResult] = []
        for payload in payloads:
            if not isinstance(payload, tuple):
                # ``gather`` hands back the exception raised by a failed lookup.
                continue
            record_type, data = payload
            if not isinstance(data, dict):
                continue
            status = data.get("Status")
            # 3 is NXDOMAIN: the hostname has no records at all.
            if isinstance(status, int) and status != 0:
                continue
            records = _answers(data, _TYPE_CODES[record_type])
            if not records:
                continue
            results.append(self._build_result(domain, record_type, records, data))
            if len(results) >= limit:
                break

        for rank, result in enumerate(results, start=1):
            result.rank = rank
        return ProviderResult(results=results)
