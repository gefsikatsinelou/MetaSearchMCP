"""CISA Known Exploited Vulnerabilities (KEV) catalog search.

The U.S. Cybersecurity and Infrastructure Security Agency (CISA) publishes a
machine-readable catalog of CVEs that have been confirmed to be exploited in
the wild.  The whole catalog is a single keyless JSON document:

``GET https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json``

The feed is small (a few thousand entries) and offers no server-side search,
so this provider downloads it once per query and filters it locally: every
whitespace-separated term in the query must appear in the CVE id, vendor,
product, vulnerability name, CWE list, or description.  Matches are returned
newest-first by the date they were added to the catalog, which makes the
provider useful for questions like "is this product being exploited, and how
recently".  It complements :mod:`metasearchmcp.providers.nvd`, which covers
the broader CVE corpus but does not flag known exploitation.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = (
    "https://www.cisa.gov/sites/default/files/feeds/"
    "known_exploited_vulnerabilities.json"
)
# The catalog currently holds ~1700 entries; we never need more than `limit`.
_MAX_API_RESULTS = 50
_NVD_DETAIL_URL = "https://nvd.nist.gov/vuln/detail/{cve_id}"


def _searchable_text(entry: dict[str, Any]) -> str:
    """Return a lowercased searchable blob for one KEV catalog entry."""
    cwes = entry.get("cwes") or []
    parts = [
        entry.get("cveID"),
        entry.get("vendorProject"),
        entry.get("product"),
        entry.get("vulnerabilityName"),
        entry.get("shortDescription"),
        " ".join(str(cwe) for cwe in cwes if cwe),
    ]
    return " ".join(str(part) for part in parts if part).lower()


class CisaKevProvider(BaseProvider):
    """Search CISA's Known Exploited Vulnerabilities (KEV) catalog.

    Keyless.  Each entry lists a CVE known to be exploited in the wild, the
    affected vendor and product, the date it was added, the remediation
    deadline, and whether it is used in known ransomware campaigns.
    """

    name = "cisa_kev"
    description = (
        "Search CISA's Known Exploited Vulnerabilities catalog for CVEs "
        "actively exploited in the wild (vendor, product, due date, "
        "ransomware use) via the keyless public feed."
    )
    tags: ClassVar[list[str]] = ["security", "cve", "us"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    def _parse(self, data: object, query: str, limit: int) -> ProviderResult:
        """Filter a KEV catalog payload to entries matching *query*.

        Every whitespace-separated token in *query* must appear somewhere in
        an entry for it to match (case-insensitive).  Matches are sorted by
        ``dateAdded`` descending before being trimmed to *limit*.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        entries = data.get("vulnerabilities")
        if not isinstance(entries, list):
            return ProviderResult(results=results)

        tokens = [token for token in query.lower().split() if token]
        matches: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            cve_id = self._clean(entry.get("cveID"))
            if not cve_id or cve_id in seen:
                continue
            if tokens and not all(token in _searchable_text(entry) for token in tokens):
                continue
            seen.add(cve_id)
            matches.append(entry)

        # ``dateAdded`` is an ISO date string, so lexical sort is chronological.
        matches.sort(key=lambda item: str(item.get("dateAdded") or ""), reverse=True)

        catalog_version = self._clean(data.get("catalogVersion"))
        for entry in matches[:limit]:
            cve_id = self._clean(entry.get("cveID"))
            vendor = self._clean(entry.get("vendorProject"))
            product = self._clean(entry.get("product"))
            name = self._clean(entry.get("vulnerabilityName"))
            added = self._clean(entry.get("dateAdded"))
            due = self._clean(entry.get("dueDate"))
            ransomware = self._clean(entry.get("knownRansomwareCampaignUse"))
            cwes = [self._clean(cwe) for cwe in (entry.get("cwes") or [])]
            cwes = [cwe for cwe in cwes if cwe]

            title = f"{cve_id}: {name}" if name else cve_id

            snippet_parts: list[str] = []
            vendor_product = f"{vendor} {product}".strip()
            if vendor_product:
                snippet_parts.append(f"Vendor/Product: {vendor_product}")
            if added:
                snippet_parts.append(f"Added: {added}")
            if due:
                snippet_parts.append(f"Due: {due}")
            if ransomware:
                snippet_parts.append(f"Ransomware: {ransomware}")
            description = self._clean(entry.get("shortDescription"))
            if description:
                snippet_parts.append(description)

            results.append(
                SearchResult(
                    title=title,
                    url=_NVD_DETAIL_URL.format(cve_id=cve_id),
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source="cisa.gov",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=self._iso_date_prefix(added or None),
                    extra={
                        "cve_id": cve_id,
                        "vendor": vendor,
                        "product": product,
                        "date_added": added,
                        "due_date": due,
                        "ransomware": ransomware,
                        "cwes": cwes,
                        "catalog_version": catalog_version,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the CISA KEV catalog for entries matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(_API_URL)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, query, limit)
