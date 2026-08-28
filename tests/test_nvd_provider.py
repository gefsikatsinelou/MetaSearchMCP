"""Unit tests for the NVD CVE provider (nvd)."""

from __future__ import annotations

from metasearchmcp.providers.nvd import NvdProvider, _cvss_summary


def _nvd_response() -> dict:
    return {
        "resultsPerPage": 3,
        "totalResults": 645,
        "vulnerabilities": [
            {
                "cve": {
                    "id": "CVE-2024-0001",
                    "published": "2024-03-01T05:00:00.000",
                    "lastModified": "2025-06-01T12:00:00.000",
                    "descriptions": [
                        {"lang": "en", "value": "A  test  vulnerability   in OpenSSL."},
                        {"lang": "es", "value": "Una vulnerabilidad de prueba."},
                    ],
                    "metrics": {
                        "cvssMetricV31": [
                            {
                                "cvssData": {
                                    "baseScore": 9.8,
                                    "baseSeverity": "CRITICAL",
                                },
                            },
                        ],
                    },
                },
            },
            {
                "cve": {
                    "id": "CVE-2024-0002",
                    "published": "2024-04-01T00:00:00.000",
                    "lastModified": "2024-04-02T00:00:00.000",
                    "descriptions": [
                        {"lang": "en", "value": "Second vulnerability."},
                    ],
                    "metrics": {
                        "cvssMetricV2": [
                            {
                                "cvssData": {"baseScore": 5.0},
                            },
                        ],
                    },
                },
            },
            # Missing CVSS metrics entirely.
            {
                "cve": {
                    "id": "CVE-2024-0003",
                    "published": "2024-05-01T00:00:00.000",
                    "lastModified": "2024-05-02T00:00:00.000",
                    "descriptions": [],
                    "metrics": {},
                },
            },
            # Missing CVE id -> skipped.
            {"cve": {"published": "2024-06-01T00:00:00.000"}},
        ],
    }


def test_nvd_parse_basic():
    p = NvdProvider()
    result = p._parse(_nvd_response(), limit=10)

    assert len(result.results) == 3
    r = result.results[0]
    assert r.title == "CVE-2024-0001"
    assert r.url == "https://nvd.nist.gov/vuln/detail/CVE-2024-0001"
    assert r.published_date == "2024-03-01"
    assert r.provider == "nvd"
    assert r.source == "nvd.nist.gov"
    assert r.rank == 1
    assert r.extra["cve_id"] == "CVE-2024-0001"
    assert r.extra["cvss_score"] == "9.8"
    assert r.extra["cvss_severity"] == "CRITICAL"
    assert r.extra["last_modified"] == "2025-06-01"
    # Whitespace is collapsed in the description.
    assert "A test vulnerability in OpenSSL." in r.snippet


def test_nvd_parse_cvss_v2_fallback():
    p = NvdProvider()
    result = p._parse(_nvd_response(), limit=10)
    r = result.results[1]
    assert r.extra["cvss_score"] == "5.0"
    # CVSS v2 has no severity field.
    assert r.extra["cvss_severity"] == ""


def test_nvd_parse_no_metrics():
    p = NvdProvider()
    result = p._parse(_nvd_response(), limit=10)
    r = result.results[2]
    assert r.extra["cvss_score"] == ""
    assert r.extra["cvss_severity"] == ""
    assert r.snippet == ""


def test_nvd_parse_empty_and_malformed():
    p = NvdProvider()
    assert p._parse({}, limit=10).results == []
    assert p._parse({"vulnerabilities": []}, limit=10).results == []
    assert p._parse({"vulnerabilities": "nope"}, limit=10).results == []
    # Non-dict entries are skipped defensively.
    assert p._parse({"vulnerabilities": [42]}, limit=10).results == []


def test_nvd_parse_respects_limit():
    p = NvdProvider()
    result = p._parse(_nvd_response(), limit=2)
    assert len(result.results) == 2


def test_nvd_parse_prefers_v31_over_v30():
    metrics = {
        "cvssMetricV30": [{"cvssData": {"baseScore": 7.5, "baseSeverity": "HIGH"}}],
        "cvssMetricV31": [{"cvssData": {"baseScore": 9.1, "baseSeverity": "CRITICAL"}}],
    }
    assert _cvss_summary(metrics) == ("9.1", "CRITICAL")


def test_cvss_summary_empty():
    assert _cvss_summary({}) == ("", "")
    assert _cvss_summary({"cvssMetricV31": []}) == ("", "")
