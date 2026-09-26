"""Certificate Transparency certificate search for a domain name.

crt.sh indexes every certificate that has been submitted to a public
Certificate Transparency log, so "which TLS certificates have been issued for
this domain" is a single keyless request::

    GET https://crt.sh/?q=example.com&output=json

The reply is a JSON array of log entries; each entry names the issuing CA
(``issuer_ca_id`` and the X.500 ``issuer_name``), the certificate's
``common_name`` together with the newline-separated ``name_value`` block of
subject alternative names, its ``not_before``/``not_after`` validity window,
the ``serial_number`` and the CT log entry ``id``.

Unlike :mod:`metasearchmcp.providers.rdap`, which reports who *registered* a
domain, and :mod:`metasearchmcp.providers.dns`, which reports how a domain
currently *resolves*, this provider reports the certificates publicly logged
for a domain — the usual way to discover subdomains and to check what a host
presents over TLS.  Because the same certificate is written to several log
shards, entries are deduplicated by serial number.  No API key is required.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://crt.sh/"
_DETAIL_URL = "https://crt.sh/?id={entry_id}"

# RFC 1035 label; the TLD is either alphabetic or a punycode ``xn--`` label.
_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_TLD_RE = re.compile(r"(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})")


def normalize_domain(query: str) -> str | None:
    """Return the hostname contained in *query*, else ``None``.

    Accepts what agents usually paste: a bare hostname (``example.com``), a
    URL (``https://www.example.com/path?q=1``), a host with a port
    (``example.com:443``) or a wildcard pattern (``*.example.com``).  The
    ``www.`` prefix is kept, because crt.sh indexes certificates per name and
    the certificates for ``www.example.com`` are a different set from those
    for ``example.com``.  Anything that is not a plausible hostname after that
    cleanup — text with spaces, bare labels, IP addresses — yields ``None``,
    so the provider never sends a request crt.sh cannot answer.
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
    # A wildcard query names the same set of certificates as its parent name.
    candidate = candidate.strip(".").removeprefix("*.").removeprefix("%.")
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


def _str(value: object) -> str | None:
    """Return a whitespace-normalized non-empty string, else ``None``."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _names(value: object) -> list[str]:
    """Split the crt.sh ``name_value`` SAN block into unique lowercased names."""
    if not isinstance(value, str):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for line in value.splitlines():
        name = line.strip().lower()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _entry_names(entry: dict[str, Any]) -> list[str]:
    """Return the SANs of *entry*, with its common name first when present."""
    names = _names(entry.get("name_value"))
    common_name = _str(entry.get("common_name"))
    if common_name is not None:
        common = common_name.lower()
        names = [common, *(name for name in names if name != common)]
    return names


def _matches_domain(name: str, domain: str) -> bool:
    """Return True when *name* is *domain* itself, a wildcard or a subdomain."""
    base = name.removeprefix("*.").strip(".")
    return base == domain or base.endswith(f".{domain}")


def _dedupe_key(entry: dict[str, Any]) -> tuple[object, ...]:
    """Return the identity of a log entry, preferring the certificate serial."""
    serial = _str(entry.get("serial_number"))
    if serial:
        return ("serial", serial.lower())
    return (
        "fallback",
        entry.get("issuer_ca_id"),
        _str(entry.get("common_name")),
        _str(entry.get("not_before")),
        _str(entry.get("not_after")),
    )


def _matching_entries(payload: object, domain: str) -> list[dict[str, Any]]:
    """Return the deduplicated log entries whose names cover *domain*.

    crt.sh identity search also answers names that merely *contain* the query
    (``testexample.com`` for ``example.com``), so entries are kept only when
    one of their names is the domain itself, a wildcard over it or a subdomain
    of it.  Each returned entry gains a ``names`` list holding its SANs.
    """
    if not isinstance(payload, list):
        return []
    entries: list[dict[str, Any]] = []
    seen: set[tuple[object, ...]] = set()
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        names = _entry_names(raw)
        if not any(_matches_domain(name, domain) for name in names):
            continue
        key = _dedupe_key(raw)
        if key in seen:
            continue
        seen.add(key)
        entries.append({**raw, "names": names})
    return entries


def _issuer_common_name(issuer_name: object) -> str | None:
    """Extract the ``CN=`` component of an X.500 issuer name, else ``None``."""
    cleaned = _str(issuer_name)
    if not cleaned:
        return None
    for part in cleaned.split(","):
        piece = part.strip()
        if piece.upper().startswith("CN="):
            value = piece[3:].strip()
            if value:
                return value
    return None


def _is_expired(not_after: object, now: str | None = None) -> bool:
    """Return True when the ISO ``not_after`` timestamp lies in the past.

    Comparison is a plain string comparison, which is exact for the
    ``YYYY-MM-DDTHH:MM:SS`` stamps crt.sh emits.  *now* is only passed by
    tests; production callers use the current UTC time.
    """
    stamp = _str(not_after)
    if not stamp:
        return False
    reference = now or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    return stamp < reference


class CrtShProvider(BaseProvider):
    """Search Certificate Transparency logs for a domain's TLS certificates.

    Keyless.  Each result is one distinct logged certificate (deduplicated by
    serial number) and carries its common name and SANs, the issuing CA, the
    validity window, the serial number and whether it has already expired.
    """

    name = "crtsh"
    description = (
        "Search public Certificate Transparency logs (crt.sh) for the TLS "
        "certificates issued for a domain: certificate common name and subject "
        "alternative names (useful for subdomain discovery), issuing CA, "
        "validity window and serial number, with no API key required. Accepts "
        "'example.com', 'https://example.com/path' or '*.example.com'."
    )
    tags: ClassVar[list[str]] = ["security", "network", "web", "tls"]

    @staticmethod
    def _snippet(
        names: list[str],
        issuer_cn: str | None,
        not_before: str | None,
        not_after: str | None,
        expired: bool,
    ) -> str:
        """Compose the snippet describing one logged certificate."""
        parts: list[str] = []
        if issuer_cn:
            parts.append(f"Issuer: {issuer_cn}")
        if not_before or not_after:
            parts.append(f"Valid: {not_before or '?'} to {not_after or '?'}")
        if names:
            parts.append(f"Names: {', '.join(names)}")
        if expired:
            parts.append("Expired")
        if not parts:
            parts.append("Certificate Transparency log entry.")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(self, entry: dict[str, Any], domain: str) -> SearchResult:
        """Build the :class:`SearchResult` for one logged certificate."""
        names: list[str] = list(entry.get("names") or [])
        common_name = _str(entry.get("common_name")) or (names[0] if names else domain)
        issuer_name = _str(entry.get("issuer_name"))
        issuer_cn = _issuer_common_name(issuer_name)
        not_before = _str(entry.get("not_before"))
        not_after = _str(entry.get("not_after"))
        expired = _is_expired(not_after)
        entry_id = entry.get("id")
        url = (
            _DETAIL_URL.format(entry_id=entry_id)
            if isinstance(entry_id, int)
            else _API_URL
        )

        return SearchResult(
            title=f"TLS certificate for {common_name}",
            url=url,
            snippet=self._snippet(names, issuer_cn, not_before, not_after, expired),
            source="crt.sh",
            provider=self.name,
            extra={
                "domain": domain,
                "common_name": common_name,
                "names": names,
                "matched_names": [
                    name for name in names if _matches_domain(name, domain)
                ],
                "certificate_id": entry_id if isinstance(entry_id, int) else None,
                "serial_number": _str(entry.get("serial_number")),
                "issuer_ca_id": entry.get("issuer_ca_id"),
                "issuer_name": issuer_name,
                "issuer_common_name": issuer_cn,
                "not_before": not_before,
                "not_after": not_after,
                "expired": expired,
            },
        )

    def _parse(self, payload: object, domain: str) -> ProviderResult:
        """Parse a crt.sh JSON payload for *domain* into structured results."""
        results = [
            self._build_result(entry, domain)
            for entry in _matching_entries(payload, domain)
        ]
        for rank, result in enumerate(results, start=1):
            result.rank = rank
        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Look up the certificates logged for the domain named by *query*.

        Queries that name no hostname, and domains that have no logged
        certificate, return an empty result set instead of an error.
        """
        domain = normalize_domain(query)
        if domain is None:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results)
        async with self._client() as client:
            resp = await client.get(_API_URL, params={"q": domain, "output": "json"})
            resp.raise_for_status()
            payload = resp.json()

        result = self._parse(payload, domain)
        result.results = result.results[:limit]
        return result
