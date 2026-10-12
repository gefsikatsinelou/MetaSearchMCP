"""IP geolocation and network ownership for a single IP address via ipwho.is.

ipwho.is (ipwho.is) is a free, keyless IP-geolocation service.  A lookup is a
single request::

    GET https://ipwho.is/{ip}

The reply describes where an address is and who announces it: the continent,
country (with ISO code and calling code), region, city, postal code, latitude
and longitude, whether the address lies in the EU, the autonomous system number
together with the organisation/ISP/domain that originate the prefix, the local
timezone and the country flag.  Reserved/private ranges answer ``200`` with
``"success": false`` and a ``message`` such as ``"Reserved range"``.

Unlike :mod:`metasearchmcp.providers.internetdb`, which reports a host's
*exposure* (open ports, CPEs, known CVEs), this provider reports a host's
*geography and network ownership*, so the two complement each other for an IP
intelligence question.  The query must be an IP address (bare IPv4/IPv6
literals, bracketed IPv6 literals and URLs such as ``https://8.8.8.8/status``
are all accepted); host names are not resolved.  No API key is required.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider
from .internetdb import normalize_ip

_API_URL = "https://ipwho.is/{ip}"


def _str(value: object) -> str | None:
    """Return a whitespace-normalized non-empty string, else ``None``."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _number(value: object) -> float | None:
    """Return *value* as a float when it is a real number, else ``None``.

    Booleans are rejected even though they are ``int`` subclasses, so a JSON
    ``true``/``false`` never masquerades as a coordinate.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _asn(value: object) -> int | None:
    """Return *value* as an AS number when it is a real integer, else ``None``."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


class IpWhoisProvider(BaseProvider):
    """Look up the geolocation and network ownership of a single IP address.

    Keyless.  The single result carries the continent, country, region, city,
    postal code, coordinates, EU membership, the ASN and organisation/ISP
    behind the prefix, the local timezone and the country flag.
    """

    name = "ipwhois"
    description = (
        "Look up IP geolocation and network ownership via ipwho.is: continent, "
        "country, region, city, postal code, coordinates, EU membership, the "
        "ASN and ISP/organisation behind the address, the local timezone and "
        "the country flag, with no API key required. Accepts an IP address "
        "such as '8.8.8.8' or 'https://8.8.8.8/status'."
    )
    tags: ClassVar[list[str]] = ["network", "geo", "web"]

    @staticmethod
    def _snippet(
        data: dict[str, Any],
        connection: dict[str, Any],
        timezone: dict[str, Any],
    ) -> str:
        """Compose the snippet describing where *data*'s address is and who runs it."""
        parts: list[str] = []

        country = _str(data.get("country"))
        country_code = _str(data.get("country_code"))
        if country:
            parts.append(f"{country} ({country_code})" if country_code else country)

        place = ", ".join(
            value
            for value in (_str(data.get("city")), _str(data.get("region")))
            if value
        )
        if place:
            parts.append(place)

        postal = _str(data.get("postal"))
        if postal:
            parts.append(f"Postal: {postal}")

        latitude = _number(data.get("latitude"))
        longitude = _number(data.get("longitude"))
        if latitude is not None and longitude is not None:
            parts.append(f"{latitude}, {longitude}")

        org = _str(connection.get("org"))
        isp = _str(connection.get("isp"))
        if isp and isp != org:
            parts.append(f"ISP: {isp}")
        if org:
            parts.append(org)

        asn = _asn(connection.get("asn"))
        if asn is not None:
            parts.append(f"AS{asn}")

        tzid = _str(timezone.get("id"))
        if tzid:
            parts.append(tzid)

        if data.get("is_eu") is True:
            parts.append("EU")

        if not parts:
            parts.append("No geolocation data recorded for this address.")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(self, data: dict[str, Any], ip: str) -> SearchResult:
        """Build the single :class:`SearchResult` for *ip* from ipwho.is data."""
        connection = data.get("connection")
        connection = connection if isinstance(connection, dict) else {}
        timezone = data.get("timezone")
        timezone = timezone if isinstance(timezone, dict) else {}
        flag = data.get("flag")
        flag = flag if isinstance(flag, dict) else {}

        return SearchResult(
            title=f"IP geolocation: {ip}",
            url=_API_URL.format(ip=ip),
            snippet=self._snippet(data, connection, timezone),
            source="ipwho.is",
            rank=1,
            provider=self.name,
            extra={
                "ip": ip,
                "type": _str(data.get("type")),
                "continent": _str(data.get("continent")),
                "country": _str(data.get("country")),
                "country_code": _str(data.get("country_code")),
                "region": _str(data.get("region")),
                "city": _str(data.get("city")),
                "postal": _str(data.get("postal")),
                "latitude": _number(data.get("latitude")),
                "longitude": _number(data.get("longitude")),
                "is_eu": data.get("is_eu") is True,
                "capital": _str(data.get("capital")),
                "calling_code": _str(data.get("calling_code")),
                "asn": _asn(connection.get("asn")),
                "organization": _str(connection.get("org")),
                "isp": _str(connection.get("isp")),
                "domain": _str(connection.get("domain")),
                "timezone": _str(timezone.get("id")),
                "utc_offset": _str(timezone.get("utc")),
                "flag": _str(flag.get("emoji")),
                "flag_image": _str(flag.get("img")),
            },
        )

    def _parse(self, data: object, ip: str) -> ProviderResult:
        """Parse an ipwho.is payload for *ip* into a result set.

        The payload must be an object with ``"success": true``; reserved ranges
        and unknown addresses carry ``"success": false`` and yield no results.
        """
        if not isinstance(data, dict) or data.get("success") is not True:
            return ProviderResult(results=[])
        return ProviderResult(results=[self._build_result(data, ip)])

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Look up geolocation data for the IP address contained in *query*.

        Queries that do not contain an IP address, and addresses that ipwho.is
        cannot resolve (reserved ranges, unknown hosts), return an empty result
        set instead of an error.
        """
        ip = normalize_ip(query)
        if ip is None:
            return ProviderResult(results=[])

        async with self._client() as client:
            resp = await client.get(_API_URL.format(ip=ip))
            # ipwho.is answers 404 for addresses it does not know at all.
            if resp.status_code == 404:
                return ProviderResult(results=[])
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError:
                return ProviderResult(results=[])

        return self._parse(data, ip)
