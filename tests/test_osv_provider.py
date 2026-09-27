"""Unit tests for the OSV.dev open source vulnerability search provider."""

from __future__ import annotations

import json

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.osv import (
    _NAME_RE as NAME_RE,
)
from metasearchmcp.providers.osv import (
    OsvProvider,
    _affected_entries,
    _clean_text,
    _cvss,
    _excerpt,
    _severity_label,
    _split_version,
    _str_list,
    build_query,
    parse_ecosystem,
    parse_vulnerability_id,
)

_LODASH: dict[str, object] = {
    "id": "GHSA-jf85-cpcp-j695",
    "summary": "Prototype Pollution in lodash",
    "details": (
        "Versions of `lodash` before 4.17.12 are vulnerable to Prototype\n"
        "Pollution.  The function `defaultsDeep` allows a malicious user to \n"
        "modify the prototype of `Object`."
    ),
    "aliases": ["CVE-2019-10744", "SNYK-JS-LODASH-450202", "CVE-2019-10744"],
    "published": "2019-07-10T19:45:23Z",
    "modified": "2026-09-10T03:47:55.238868631Z",
    "severity": [
        {"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:H"}
    ],
    "database_specific": {
        "cwe_ids": ["CWE-1321", "CWE-20"],
        "severity": "CRITICAL",
        "github_reviewed": True,
    },
    "references": [
        {"type": "ADVISORY", "url": "https://nvd.nist.gov/vuln/detail/CVE-2019-10744"},
        {"type": "WEB", "url": "https://github.com/lodash/lodash/pull/4336"},
    ],
    "affected": [
        {
            "package": {
                "name": "lodash",
                "ecosystem": "npm",
                "purl": "pkg:npm/lodash",
            },
            "ranges": [
                {
                    "type": "SEMVER",
                    "events": [{"introduced": "0"}, {"fixed": "4.17.12"}],
                },
            ],
            "database_specific": {
                "source": "https://github.com/github/advisory-database"
            },
        },
        {
            "package": {"name": "lodash", "ecosystem": "npm"},
            "ranges": [
                {
                    "type": "SEMVER",
                    "events": [{"introduced": "3.0.0"}, {"fixed": "3.10.2"}],
                },
            ],
            "versions": ["3.0.0", "3.1.0"],
        },
    ],
}

_QUERY_RESPONSE: dict[str, object] = {"vulns": [_LODASH, {"id": ""}, "junk"]}

_OSV_FUZZ: dict[str, object] = {
    "id": "OSV-2020-111",
    "summary": "Heap-use-after-free in poppler",
    "details": "An OSS-Fuzz report.",
    "published": "2020-06-01T00:00:00Z",
    "affected": [
        {
            "package": {"name": "poppler", "ecosystem": "OSS-Fuzz"},
            "ranges": [
                {
                    "type": "GIT",
                    "events": [{"introduced": "abc123"}, {"fixed": "def456"}],
                },
            ],
        },
    ],
}

_WITHOUT_DATE: dict[str, object] = {
    "id": "PYSEC-2021-1",
    "summary": "Undated advisory",
    "affected": [{"package": {"name": "requests", "ecosystem": "PyPI"}}],
}


def _provider() -> OsvProvider:
    return OsvProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "osv"
    assert p.tags == ["security", "vulnerabilities", "code", "packages"]
    assert p.is_available() is True
    assert "OSV.dev" in p.description
    assert "GHSA-jf85-cpcp-j695" in p.description


def test_parse_vulnerability_id_accepts_ids() -> None:
    assert parse_vulnerability_id("CVE-2021-44228") == "CVE-2021-44228"
    assert parse_vulnerability_id("GHSA-jf85-cpcp-j695") == "GHSA-jf85-cpcp-j695"
    assert parse_vulnerability_id("PYSEC-2021-1") == "PYSEC-2021-1"
    assert parse_vulnerability_id("OSV-2020-111") == "OSV-2020-111"
    assert parse_vulnerability_id("UBUNTU-CVE-2021-44228") == "UBUNTU-CVE-2021-44228"


def test_parse_vulnerability_id_rejects_other_tokens() -> None:
    assert parse_vulnerability_id("") is None
    assert parse_vulnerability_id("lodash") is None
    assert parse_vulnerability_id("node-fetch") is None
    assert parse_vulnerability_id("go-lang") is None
    assert parse_vulnerability_id("CVE-") is None
    assert parse_vulnerability_id("CVE-2021-44228 lodash") is None
    assert parse_vulnerability_id("lodash-4.17.11") is None


def test_parse_ecosystem_aliases() -> None:
    assert parse_ecosystem("pypi") == "PyPI"
    assert parse_ecosystem(" Python ") == "PyPI"
    assert parse_ecosystem("crates.io") == "crates.io"
    assert parse_ecosystem("rust") == "crates.io"
    assert parse_ecosystem("github-actions") == "GitHub Actions"
    assert parse_ecosystem("maven") == "Maven"
    assert parse_ecosystem("golang.org") is None
    assert parse_ecosystem("") is None


def test_split_version_variants() -> None:
    assert _split_version("lodash", NAME_RE) == ("lodash", "")
    assert _split_version("lodash@4.17.11", NAME_RE) == ("lodash", "4.17.11")
    assert _split_version("@scope/pkg", NAME_RE) == ("@scope/pkg", "")
    assert _split_version("@scope/pkg@1.2.3", NAME_RE) == ("@scope/pkg", "1.2.3")
    assert _split_version("golang.org/x/text", NAME_RE) == (
        "golang.org/x/text",
        "",
    )
    assert _split_version("requests 2.19.0", NAME_RE) == ("requests", "2.19.0")
    assert _split_version("requests 2.19.0 extra", NAME_RE) is None
    assert _split_version("", NAME_RE) is None
    # A dangling "@" with no version is treated as a versionless lookup.
    assert _split_version("lodash@", NAME_RE) == ("lodash", "")
    assert _split_version("@scope/pkg@", NAME_RE) == ("@scope/pkg", "")
    assert _split_version("lodash 4.17.11", NAME_RE) == ("lodash", "4.17.11")


def test_build_query_recognizes_advisory_ids() -> None:
    plan = build_query(" CVE-2021-44228 ")
    assert plan is not None
    assert (plan.kind, plan.value) == ("id", "CVE-2021-44228")


def test_build_query_parses_ecosystem_forms() -> None:
    plan = build_query("pypi:requests@2.19.0")
    assert plan is not None
    assert (plan.kind, plan.value, plan.ecosystem, plan.version) == (
        "package",
        "requests",
        "PyPI",
        "2.19.0",
    )

    plan = build_query("npm/lodash")
    assert plan is not None
    assert (plan.kind, plan.value, plan.ecosystem, plan.version) == (
        "package",
        "lodash",
        "npm",
        "",
    )

    plan = build_query("npm lodash 4.17.11")
    assert plan is not None
    assert (plan.kind, plan.value, plan.ecosystem, plan.version) == (
        "package",
        "lodash",
        "npm",
        "4.17.11",
    )

    plan = build_query("go golang.org/x/text")
    assert plan is not None
    assert (plan.kind, plan.value, plan.ecosystem) == (
        "package",
        "golang.org/x/text",
        "Go",
    )


def test_build_query_parses_maven_coordinates() -> None:
    plan = build_query("maven:org.apache.logging.log4j:log4j-core@2.14.1")
    assert plan is not None
    assert (plan.kind, plan.value, plan.ecosystem, plan.version) == (
        "package",
        "org.apache.logging.log4j:log4j-core",
        "Maven",
        "2.14.1",
    )


def test_build_query_parses_bare_names() -> None:
    plan = build_query("lodash")
    assert plan is not None
    assert (plan.kind, plan.value, plan.version) == ("name", "lodash", "")

    plan = build_query("lodash@4.17.11")
    assert plan is not None
    assert (plan.kind, plan.value, plan.version) == ("name", "lodash", "4.17.11")

    plan = build_query("lodash 4.17.11")
    assert plan is not None
    assert (plan.kind, plan.value, plan.version) == ("name", "lodash", "4.17.11")

    plan = build_query("@scope/pkg")
    assert plan is not None
    assert (plan.kind, plan.value) == ("name", "@scope/pkg")

    plan = build_query("golang.org/x/text")
    assert plan is not None
    assert (plan.kind, plan.value) == ("name", "golang.org/x/text")


def test_build_query_strips_trailing_noise_words() -> None:
    plan = build_query("lodash vulnerabilities")
    assert plan is not None
    assert (plan.kind, plan.value) == ("name", "lodash")

    plan = build_query("log4j security advisory")
    assert plan is not None
    assert (plan.kind, plan.value) == ("name", "log4j")


def test_build_query_rejects_free_text() -> None:
    assert build_query("") is None
    assert build_query("   ") is None
    assert build_query("prototype pollution in lodash") is None
    assert build_query("lodash@4.17.11 extra token") is None
    assert build_query("something:@@@") is None


def test_value_coercion_helpers() -> None:
    assert _clean_text("  a \n b ") == "a b"
    assert _clean_text(None) == ""
    assert _clean_text(7) == ""
    assert _excerpt("short", 10) == "short"
    assert _excerpt("truncate me here", 8) == "truncate"
    assert _str_list(["a", " a ", "", 5, "b"]) == ["a", "b"]
    assert _str_list("nope") == []


def test_severity_and_cvss_helpers() -> None:
    assert _severity_label(_LODASH) == "CRITICAL"
    assert _severity_label(
        {"affected": [{"ecosystem_specific": {"severity": "High"}}]}
    ) == ("High")
    assert _severity_label({}) == ""
    assert _cvss(_LODASH) == (
        "CVSS_V3",
        "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:H",
    )
    assert _cvss({"severity": [{"type": "CVSS_V2", "score": "AV:N"}]}) == (
        "CVSS_V2",
        "AV:N",
    )
    assert _cvss({}) == ("", "")
    assert _cvss({"severity": "junk"}) == ("", "")


def test_affected_entries_collect_ranges_and_fixed_versions() -> None:
    entries = _affected_entries(_LODASH, "npm")
    assert len(entries) == 2
    first = entries[0]
    assert first["ecosystem"] == "npm"
    assert first["name"] == "lodash"
    assert first["purl"] == "pkg:npm/lodash"
    assert first["fixed_versions"] == ["4.17.12"]
    assert first["range_types"] == ["SEMVER"]
    assert first["vulnerable_versions_listed"] == 0
    assert entries[1]["fixed_versions"] == ["3.10.2"]
    assert entries[1]["vulnerable_versions_listed"] == 2


def test_affected_entries_fall_back_to_default_ecosystem() -> None:
    entries = _affected_entries(
        {"affected": [{"package": {"name": "lodash"}}]},
        "PyPI",
    )
    assert entries == [
        {
            "ecosystem": "PyPI",
            "name": "lodash",
            "purl": None,
            "fixed_versions": [],
            "range_types": [],
            "vulnerable_versions_listed": 0,
        },
    ]
    assert _affected_entries({}) == []


def test_parse_builds_advisory_results() -> None:
    result = _provider()._parse_vulns(_QUERY_RESPONSE, "npm", 10)

    assert len(result.results) == 1
    first = result.results[0]
    assert first.title == "Prototype Pollution in lodash (GHSA-jf85-cpcp-j695)"
    assert first.url == "https://osv.dev/vulnerability/GHSA-jf85-cpcp-j695"
    assert first.source == "osv.dev"
    assert first.provider == "osv"
    assert first.rank == 1
    assert first.published_date == "2019-07-10"
    assert "Severity: CRITICAL" in first.snippet
    assert "CVSS V3: CVSS:3.1/AV:N" in first.snippet
    assert "modify the prototype of `Object`" in first.snippet
    assert (
        "Affects npm:lodash (fixed in 4.17.12), npm:lodash (fixed in 3.10.2)"
        in first.snippet
    )
    assert "Aliases: CVE-2019-10744, SNYK-JS-LODASH-450202" in first.snippet
    assert "Published 2019-07-10" in first.snippet
    assert first.extra["id"] == "GHSA-jf85-cpcp-j695"
    assert first.extra["aliases"] == ["CVE-2019-10744", "SNYK-JS-LODASH-450202"]
    assert first.extra["severity"] == "CRITICAL"
    assert first.extra["cvss_type"] == "CVSS_V3"
    assert first.extra["cwe_ids"] == ["CWE-1321", "CWE-20"]
    assert first.extra["ecosystems"] == ["npm"]
    assert first.extra["fixed_versions"] == ["4.17.12", "3.10.2"]
    assert first.extra["reference_count"] == 2
    assert first.extra["modified"] == "2026-09-10T03:47:55.238868631Z"
    assert first.extra["withdrawn"] is None


def test_parse_single_advisory_payload() -> None:
    result = _provider()._parse_vulns(_LODASH, "", 1)

    assert len(result.results) == 1
    assert (
        result.results[0].title == "Prototype Pollution in lodash (GHSA-jf85-cpcp-j695)"
    )


def test_parse_sorts_newest_first_and_respects_limit() -> None:
    payload = {"vulns": [_LODASH, _OSV_FUZZ, _WITHOUT_DATE]}
    result = _provider()._parse_vulns(payload, "", 2)

    assert [r.extra["id"] for r in result.results] == [
        "OSV-2020-111",
        "GHSA-jf85-cpcp-j695",
    ]
    assert [r.rank for r in result.results] == [1, 2]

    full = _provider()._parse_vulns(payload, "", 10)
    assert full.results[-1].extra["id"] == "PYSEC-2021-1"
    assert full.results[-1].published_date is None


def test_parse_untitled_advisory_uses_id_as_title() -> None:
    result = _provider()._parse_vulns({"vulns": [_WITHOUT_DATE]}, "", 10)

    assert result.results[0].title == "Undated advisory (PYSEC-2021-1)"


def test_parse_malformed_payloads() -> None:
    p = _provider()
    assert p._parse_vulns("junk", "", 10).results == []
    assert p._parse_vulns(None, "", 10).results == []
    assert p._parse_vulns({"vulns": "junk"}, "", 10).results == []
    assert p._parse_vulns({}, "", 10).results == []


@pytest.mark.asyncio
async def test_search_fetches_advisory_by_id(respx_mock) -> None:
    import respx

    route = respx_mock.get(
        "https://api.osv.dev/v1/vulns/GHSA-jf85-cpcp-j695",
    ).mock(return_value=respx.MockResponse(200, json=_LODASH))

    result = await _provider().search(
        "GHSA-jf85-cpcp-j695",
        SearchParams(num_results=5),
    )

    assert len(result.results) == 1
    assert len(respx_mock.calls) == 1
    assert route.calls[0].request.method == "GET"


@pytest.mark.asyncio
async def test_search_unknown_advisory_id_returns_empty(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.osv.dev/v1/vulns/CVE-1999-0001").mock(
        return_value=respx.MockResponse(
            404,
            json={"code": 5, "message": "Vulnerability not found"},
        ),
    )

    result = await _provider().search("CVE-1999-0001", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_search_queries_one_ecosystem(respx_mock) -> None:
    import respx

    route = respx_mock.post("https://api.osv.dev/v1/query").mock(
        return_value=respx.MockResponse(200, json=_QUERY_RESPONSE),
    )

    result = await _provider().search(
        "pypi:requests@2.19.0",
        SearchParams(num_results=5),
    )

    assert len(result.results) == 1
    body = json.loads(route.calls[0].request.content)
    assert body == {
        "package": {"name": "requests", "ecosystem": "PyPI"},
        "version": "2.19.0",
    }


@pytest.mark.asyncio
async def test_search_queries_ecosystem_without_version(respx_mock) -> None:
    import respx

    route = respx_mock.post("https://api.osv.dev/v1/query").mock(
        return_value=respx.MockResponse(200, json={"vulns": []}),
    )

    result = await _provider().search("npm:lodash", SearchParams(num_results=5))

    assert result.results == []
    body = json.loads(route.calls[0].request.content)
    assert body == {"package": {"name": "lodash", "ecosystem": "npm"}}


@pytest.mark.asyncio
async def test_search_broadcasts_bare_name_and_fetches_details(respx_mock) -> None:
    import respx

    batch_route = respx_mock.post("https://api.osv.dev/v1/querybatch").mock(
        return_value=respx.MockResponse(
            200,
            json={
                "results": [
                    {"vulns": [{"id": "GHSA-jf85-cpcp-j695", "modified": "x"}]},
                    "junk",
                    {"vulns": [{"id": "OSV-2020-111"}]},
                    {"vulns": []},
                ],
            },
        ),
    )
    respx_mock.get("https://api.osv.dev/v1/vulns/GHSA-jf85-cpcp-j695").mock(
        return_value=respx.MockResponse(200, json=_LODASH),
    )
    respx_mock.get("https://api.osv.dev/v1/vulns/OSV-2020-111").mock(
        return_value=respx.MockResponse(200, json=_OSV_FUZZ),
    )

    result = await _provider().search("lodash@4.17.11", SearchParams(num_results=5))

    assert [r.extra["id"] for r in result.results] == [
        "OSV-2020-111",
        "GHSA-jf85-cpcp-j695",
    ]
    body = json.loads(batch_route.calls[0].request.content)
    assert len(body["queries"]) == 14
    assert body["queries"][0] == {
        "package": {"name": "lodash", "ecosystem": "npm"},
        "version": "4.17.11",
    }
    assert body["queries"][1] == {
        "package": {"name": "lodash", "ecosystem": "PyPI"},
        "version": "4.17.11",
    }
    assert body["queries"][2]["package"]["ecosystem"] == "Go"
    # The ecosystem of the batch bucket is reported on the result.
    by_id = {r.extra["id"]: r for r in result.results}
    assert by_id["GHSA-jf85-cpcp-j695"].extra["ecosystems"] == ["npm"]
    assert by_id["OSV-2020-111"].extra["ecosystems"] == ["OSS-Fuzz"]


@pytest.mark.asyncio
async def test_search_bare_name_skips_failed_detail_fetches(respx_mock) -> None:
    import respx

    respx_mock.post("https://api.osv.dev/v1/querybatch").mock(
        return_value=respx.MockResponse(
            200,
            json={
                "results": [
                    {"vulns": [{"id": "GHSA-jf85-cpcp-j695"}, {"id": "OSV-2020-111"}]},
                ],
            },
        ),
    )
    respx_mock.get("https://api.osv.dev/v1/vulns/GHSA-jf85-cpcp-j695").mock(
        return_value=respx.MockResponse(500, json={"message": "boom"}),
    )
    respx_mock.get("https://api.osv.dev/v1/vulns/OSV-2020-111").mock(
        return_value=respx.MockResponse(200, json=_OSV_FUZZ),
    )

    result = await _provider().search("lodash", SearchParams(num_results=5))

    assert [r.extra["id"] for r in result.results] == ["OSV-2020-111"]


@pytest.mark.asyncio
async def test_search_bare_name_without_matches(respx_mock) -> None:
    import respx

    respx_mock.post("https://api.osv.dev/v1/querybatch").mock(
        return_value=respx.MockResponse(200, json={"results": []}),
    )

    result = await _provider().search("nonexistentpackage", SearchParams(num_results=5))

    assert result.results == []
    assert len(respx_mock.calls) == 1


@pytest.mark.asyncio
async def test_search_skips_request_for_unusable_query(respx_mock) -> None:
    import respx

    respx_mock.route(host="api.osv.dev").mock(
        return_value=respx.MockResponse(200, json={"vulns": []}),
    )

    for query in ("", "   ", "prototype pollution in lodash"):
        result = await _provider().search(query, SearchParams(num_results=5))
        assert result.results == []
    assert len(respx_mock.calls) == 0


@pytest.mark.asyncio
async def test_search_raises_on_api_error(respx_mock) -> None:
    import httpx
    import respx

    respx_mock.post("https://api.osv.dev/v1/query").mock(
        return_value=respx.MockResponse(
            400,
            json={"code": 3, "message": "invalid query"},
        ),
    )

    with pytest.raises(httpx.HTTPStatusError):
        await _provider().search("pypi:requests", SearchParams(num_results=5))


def test_registry_includes_osv() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "osv" in registry
    assert registry["osv"].tags == ["security", "vulnerabilities", "code", "packages"]
