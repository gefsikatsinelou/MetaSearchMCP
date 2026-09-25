"""RDAP domain registration lookup for domain names.

RDAP (Registration Data Access Protocol) is the structured, JSON successor to
the WHOIS protocol.  The public bootstrap service at rdap.org maps a domain to
its authoritative registry and redirects there::

    GET https://rdap.org/domain/{domain}

The reply is the domain's registration record: the registrar of record, the
registry status flags (``client transfer prohibited`` and friends), the
nameservers the domain delegates to, whether DNSSEC is enabled and the
lifecycle events (registration, expiration, last changed).  Domains that have
never been registered answer ``404``.

Unlike :mod:`metasearchmcp.providers.internetdb`, which reports the open ports
and CVEs of a *host* by IP address, this provider reports the registration
metadata of a *domain name*: the usual first step when vetting a domain.  No
API key is required.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://rdap.org/domain/{domain}"
_ACCEPT = "application/rdap+json"

# RFC 1035 label; the TLD is either alphabetic or a punycode ``xn--`` label.
_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_TLD_RE = re.compile(r"(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})")


def normalize_domain(query: str) -> str | None:
    """Return the bare registrable domain contained in *query*, else ``None``.

    Accepts what agents usually paste: a bare hostname (``example.com``), a
    URL (``https://www.example.com/path?q=1``) or a host with a port
    (``example.com:443``).  Anything that is not a plausible domain name after
    that cleanup — text with spaces, bare labels, IP addresses — yields
    ``None``, so the provider never sends a request RDAP cannot answer.
    """
    candidate = query.strip().lower()
    if not candidate or any(char.isspace() for char in candidate):
        return None
    if "://" in candidate:
        candidate = candidate.split("://", 1)[1]
    candidate = candidate.split("/", 1)[0]
    candidate = candidate.rsplit("@", 1)[-1]
    # Strip a port suffix; a hostname has at most one colon (IPv6 is rejected
    # below, as it is not a domain name).
    if candidate.count(":") == 1:
        candidate = candidate.split(":", 1)[0]
    candidate = candidate.strip(".").removeprefix("www.")
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


def _status_list(value: object) -> list[str]:
    """Coerce the RDAP ``status`` array to a deduplicated list of strings."""
    if not isinstance(value, list):
        return []
    statuses: list[str] = []
    seen: set[str] = set()
    for item in value:
        cleaned = _str(item)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            statuses.append(cleaned)
    return statuses


def _nameserver_list(value: object) -> list[str]:
    """Extract the lowercased nameserver hostnames from RDAP ``nameservers``."""
    if not isinstance(value, list):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for entry in value:
        if not isinstance(entry, dict):
            continue
        name = _str(entry.get("ldhName"))
        if name and name.lower() not in seen:
            seen.add(name.lower())
            names.append(name.lower())
    return names


def _event_map(value: object) -> dict[str, str]:
    """Map RDAP lifecycle ``events`` to an ``action -> date`` dictionary.

    Actions are lowercased and have their spaces replaced with underscores,
    so ``"last changed"`` becomes ``"last_changed"``.  The first date seen for
    an action wins, which keeps the output stable across registries.
    """
    if not isinstance(value, list):
        return {}
    events: dict[str, str] = {}
    for entry in value:
        if not isinstance(entry, dict):
            continue
        action = _str(entry.get("eventAction"))
        date = _str(entry.get("eventDate"))
        if action and date:
            events.setdefault(action.lower().replace(" ", "_"), date)
    return events


def _vcard_name(value: object) -> str | None:
    """Return the ``fn`` (formatted name) of an RDAP vCard array."""
    if not isinstance(value, list) or len(value) < 2:
        return None
    properties = value[1]
    if not isinstance(properties, list):
        return None
    for prop in properties:
        if (
            isinstance(prop, list)
            and len(prop) >= 4
            and prop[0] == "fn"
            and isinstance(prop[3], str)
        ):
            cleaned = _str(prop[3])
            if cleaned:
                return cleaned
    return None


def _entity_name(entities: object, role: str) -> str | None:
    """Return the vCard name of the first entity holding *role*, else ``None``."""
    if not isinstance(entities, list):
        return None
    for entry in entities:
        if not isinstance(entry, dict):
            continue
        roles = entry.get("roles")
        if not isinstance(roles, list) or role not in roles:
            continue
        name = _vcard_name(entry.get("vcardArray"))
        if name:
            return name
    return None


def _dnssec_signed(value: object) -> bool | None:
    """Return the ``secureDNS.delegationSigned`` flag, or ``None`` when absent."""
    if isinstance(value, dict) and isinstance(value.get("delegationSigned"), bool):
        return value["delegationSigned"]
    return None


class RdapProvider(BaseProvider):
    """Look up RDAP registration data for a single domain name.

    Keyless.  Each result is one domain and carries its registrar, registry
    status flags, lifecycle dates (registration, expiration, last changed),
    delegated nameservers and DNSSEC state.
    """

    name = "rdap"
    description = (
        "Look up RDAP domain registration data for a domain name: registrar, "
        "registry status flags, registration/expiry/update dates, delegated "
        "nameservers and DNSSEC state, with no API key required."
    )
    tags: ClassVar[list[str]] = ["security", "network", "web"]

    @staticmethod
    def _snippet(
        registrar: str | None,
        statuses: list[str],
        events: dict[str, str],
        nameservers: list[str],
        dnssec: bool | None,
    ) -> str:
        """Compose the snippet describing one domain's registration record."""
        parts: list[str] = []
        if registrar:
            parts.append(f"Registrar: {registrar}")
        if statuses:
            parts.append(f"Status: {', '.join(statuses)}")
        for action, label in (
            ("registration", "Registered"),
            ("expiration", "Expires"),
            ("last_changed", "Last changed"),
        ):
            date = events.get(action)
            if date:
                parts.append(f"{label}: {date[:10]}")
        if nameservers:
            parts.append(f"Nameservers: {', '.join(nameservers)}")
        if dnssec is not None:
            parts.append(f"DNSSEC: {'signed' if dnssec else 'unsigned'}")
        if not parts:
            parts.append("No registrar, status, dates or nameservers recorded.")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(self, data: dict[str, Any], domain: str) -> SearchResult:
        """Build the single :class:`SearchResult` for *domain* from RDAP data."""
        statuses = _status_list(data.get("status"))
        events = _event_map(data.get("events"))
        nameservers = _nameserver_list(data.get("nameservers"))
        registrar = _entity_name(data.get("entities"), "registrar") or _entity_name(
            data.get("entities"), "sponsor"
        )
        dnssec = _dnssec_signed(data.get("secureDNS"))

        return SearchResult(
            title=f"RDAP: {_str(data.get('ldhName')) or domain}",
            url=_API_URL.format(domain=domain),
            snippet=self._snippet(registrar, statuses, events, nameservers, dnssec),
            source="rdap.org",
            rank=1,
            provider=self.name,
            extra={
                "domain": domain,
                "handle": _str(data.get("handle")),
                "registrar": registrar,
                "statuses": statuses,
                "status_count": len(statuses),
                "events": events,
                "registered": events.get("registration"),
                "expires": events.get("expiration"),
                "last_changed": events.get("last_changed"),
                "nameservers": nameservers,
                "dnssec_signed": dnssec,
                "has_registration_date": "registration" in events,
            },
        )

    def _parse(self, data: object, domain: str) -> ProviderResult:
        """Parse an RDAP payload for *domain* into structured results."""
        if not isinstance(data, dict):
            return ProviderResult(results=[])
        return ProviderResult(results=[self._build_result(data, domain)])

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Look up RDAP registration data for the domain name in *query*.

        Queries that do not contain a domain name, and domains that have never
        been registered, return an empty result set instead of an error.
        """
        domain = normalize_domain(query)
        if domain is None:
            return ProviderResult(results=[])

        async with self._client() as client:
            resp = await client.get(
                _API_URL.format(domain=domain),
                headers={"Accept": _ACCEPT},
            )
            # Registries answer 404 for domains they hold no record of.
            if resp.status_code == 404:
                return ProviderResult(results=[])
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, domain)
