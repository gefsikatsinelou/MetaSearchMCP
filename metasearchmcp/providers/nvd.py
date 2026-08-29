"""NVD CVE vulnerability search via the keyless NIST NVD REST API 2.0.

``GET https://services.nvd.nist.gov/rest/json/cves/2.0`` returns Common
Vulnerability and Exposures (CVE) records matching the query as JSON. The
endpoint is public and requires no API key (an optional ``apiKey`` improves
rate limits). Search is keyword-based (``keywordSearch``) against the CVE
title, descriptions, and references.

Each result carries the CVE ID, the English description, the CVSS v3 base
score/severity (falling back to v2), the publication and last-modified
dates, and the NVD detail page URL.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
# The NVD API caps resultsPerPage at 2000; keep it modest.
_MAX_API_RESULTS = 50
_NVD_DETAIL_URL = "https://nvd.nist.gov/vuln/detail/{cve_id}"


def _cvss_summary(metrics: dict[str, Any]) -> tuple[str, str]:
    """Return (score, severity) from a CVE ``metrics`` payload.

    Prefers CVSS v3.1, then v3.0, then v2.0; returns ("", "") when no
    usable metric is present.
    """
    for key in ("cvssMetricV31", "cvssMetricV30"):
        metric_list = metrics.get(key) or []
        if not metric_list:
            continue
        data = (metric_list[0] or {}).get("cvssData") or {}
        score = data.get("baseScore")
        severity = data.get("baseSeverity")
        if score is not None:
            return str(score), str(severity or "")
    metric_v2 = metrics.get("cvssMetricV2") or []
    if metric_v2:
        data = (metric_v2[0] or {}).get("cvssData") or {}
        score = data.get("baseScore")
        if score is not None:
            return str(score), ""
    return "", ""


class NvdProvider(BaseProvider):
    """Search the NIST NVD database for CVE vulnerabilities by keyword.

    Keyless. Results carry the CVE ID, English description, CVSS v3 base
    score and severity, publication/last-modified dates, and a direct NVD
    detail link.
    """

    name = "nvd"
    description = (
        "Search NIST NVD for CVE vulnerabilities by keyword — CVSS scores "
        "and severity via the keyless NVD REST API."
    )
    tags: ClassVar[list[str]] = ["security", "cve", "us"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    def _parse(self, data: dict[str, Any], limit: int) -> ProviderResult:
        """Parse a /rest/json/cves/2.0 response into structured results."""
        results: list[SearchResult] = []
        for item in (data.get("vulnerabilities") or [])[:limit]:
            if not isinstance(item, dict):
                continue
            cve = item.get("cve") or {}
            if not isinstance(cve, dict):
                continue
            cve_id = cve.get("id") or ""
            if not cve_id:
                continue

            descriptions = [
                d.get("value", "")
                for d in (cve.get("descriptions") or [])
                if d.get("lang") == "en" and d.get("value")
            ]
            description = self._clean(descriptions[0]) if descriptions else ""

            score, severity = _cvss_summary(cve.get("metrics") or {})
            snippet_parts: list[str] = []
            if score:
                snippet_parts.append(f"CVSS: {score}")
            if severity:
                snippet_parts.append(f"Severity: {severity}")
            if description:
                snippet_parts.append(description)
            snippet = " | ".join(snippet_parts)

            results.append(
                SearchResult(
                    title=cve_id,
                    url=_NVD_DETAIL_URL.format(cve_id=cve_id),
                    snippet=snippet,
                    source="nvd.nist.gov",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=self._iso_date_prefix(cve.get("published")),
                    extra={
                        "cve_id": cve_id,
                        "cvss_score": score,
                        "cvss_severity": severity,
                        "last_modified": self._iso_date_prefix(cve.get("lastModified")),
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the NVD for CVEs matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={
                    "keywordSearch": query,
                    "resultsPerPage": str(limit),
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit)
