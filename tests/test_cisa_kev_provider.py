"""Unit tests for the CISA KEV (Known Exploited Vulnerabilities) provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.cisa_kev import CisaKevProvider, _searchable_text

_SAMPLE_RESPONSE: dict[str, object] = {
    "title": "CISA Catalog of Known Exploited Vulnerabilities",
    "catalogVersion": "2024.01.02",
    "dateReleased": "2024-01-02T19:00:05.1949Z",
    "count": 3,
    "vulnerabilities": [
        {
            "cveID": "CVE-2024-0002",
            "vendorProject": "Apache",
            "product": "HTTP Server",
            "vulnerabilityName": "Apache HTTP Server path traversal",
            "dateAdded": "2024-01-10",
            "shortDescription": "A  path   traversal issue.",
            "requiredAction": "Apply updates.",
            "dueDate": "2024-01-31",
            "knownRansomwareCampaignUse": "Unknown",
            "cwes": ["CWE-22"],
        },
        {
            "cveID": "CVE-2024-0001",
            "vendorProject": "Microsoft",
            "product": "Windows",
            "vulnerabilityName": "Microsoft Windows privilege escalation",
            "dateAdded": "2024-01-05",
            "shortDescription": "A privilege escalation flaw.",
            "requiredAction": "Apply updates.",
            "dueDate": "2024-01-26",
            "knownRansomwareCampaignUse": "Known",
            "cwes": ["CWE-269", "CWE-20"],
        },
        {
            # Missing cveID -> skipped.
            "vendorProject": "Microsoft",
            "product": "Windows",
        },
        # Duplicate of the first CVE -> deduplicated.
        {
            "cveID": "CVE-2024-0002",
            "vendorProject": "Apache",
            "product": "HTTP Server",
            "dateAdded": "2024-01-10",
        },
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"catalogVersion": "x", "vulnerabilities": []}


def _provider() -> CisaKevProvider:
    return CisaKevProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "cisa_kev"
    assert p.tags == ["security", "cve", "us"]
    assert p.is_available() is True


def test_searchable_text_is_lowercased_and_covers_fields() -> None:
    text = _searchable_text(
        {
            "cveID": "CVE-2024-0001",
            "vendorProject": "Microsoft",
            "product": "Windows",
            "vulnerabilityName": "Escalation",
            "shortDescription": "A flaw",
            "cwes": ["CWE-269"],
        },
    )
    for fragment in ("cve-2024-0001", "microsoft", "windows", "escalation", "cwe-269"):
        assert fragment in text


def test_parse_orders_newest_added_first() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, "", limit=10)

    assert [r.extra["cve_id"] for r in result.results] == [
        "CVE-2024-0002",
        "CVE-2024-0001",
    ]
    assert result.results[0].rank == 1
    assert result.results[1].rank == 2


def test_parse_single_entry_fields() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, "privilege escalation", limit=10)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "CVE-2024-0001: Microsoft Windows privilege escalation"
    assert r.url == "https://nvd.nist.gov/vuln/detail/CVE-2024-0001"
    assert r.provider == "cisa_kev"
    assert r.source == "cisa.gov"
    assert r.published_date == "2024-01-05"
    assert "Vendor/Product: Microsoft Windows" in r.snippet
    assert "Added: 2024-01-05" in r.snippet
    assert "Due: 2024-01-26" in r.snippet
    assert "Ransomware: Known" in r.snippet
    assert r.extra["vendor"] == "Microsoft"
    assert r.extra["product"] == "Windows"
    assert r.extra["due_date"] == "2024-01-26"
    assert r.extra["ransomware"] == "Known"
    assert r.extra["cwes"] == ["CWE-269", "CWE-20"]
    assert r.extra["catalog_version"] == "2024.01.02"


def test_parse_matching_is_case_insensitive_and_requires_all_tokens() -> None:
    p = _provider()

    # Case-insensitive vendor match.
    assert len(p._parse(_SAMPLE_RESPONSE, "MICROSOFT", limit=10).results) == 1
    # All tokens must be present.
    assert p._parse(_SAMPLE_RESPONSE, "microsoft apache", limit=10).results == []
    # CWE token matches the Apache entry.
    assert len(p._parse(_SAMPLE_RESPONSE, "cwe-22", limit=10).results) == 1


def test_parse_empty_query_returns_all_newest_first() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, "   ", limit=10)
    assert [r.extra["cve_id"] for r in result.results] == [
        "CVE-2024-0002",
        "CVE-2024-0001",
    ]


def test_parse_respects_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, "", limit=1)
    assert len(result.results) == 1
    assert result.results[0].extra["cve_id"] == "CVE-2024-0002"


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse({}, "x", limit=10).results == []
    assert p._parse(_EMPTY_RESPONSE, "x", limit=10).results == []
    assert p._parse({"vulnerabilities": "nope"}, "x", limit=10).results == []
    assert p._parse({"vulnerabilities": [42, None]}, "x", limit=10).results == []
    assert p._parse("junk", "x", limit=10).results == []


def test_parse_missing_optional_fields_still_yields_result() -> None:
    data = {"vulnerabilities": [{"cveID": "CVE-2024-9999", "dateAdded": "2024-02-01"}]}
    result = _provider()._parse(data, "", limit=10)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "CVE-2024-9999"
    assert r.snippet == "Added: 2024-02-01"
    assert r.extra["cwes"] == []
    assert r.published_date == "2024-02-01"


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get(
        "https://www.cisa.gov/sites/default/files/feeds/"
        "known_exploited_vulnerabilities.json",
    ).mock(return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE))

    result = await _provider().search("apache", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "cisa_kev"
    assert len(respx_mock.calls) == 1


@pytest.mark.asyncio
async def test_search_no_match(respx_mock) -> None:
    import respx

    respx_mock.get(
        "https://www.cisa.gov/sites/default/files/feeds/"
        "known_exploited_vulnerabilities.json",
    ).mock(return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE))

    result = await _provider().search("zzzz", SearchParams(num_results=5))
    assert result.results == []
