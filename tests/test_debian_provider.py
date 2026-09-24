"""Unit tests for the Debian source package search provider."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.debian import DebianProvider

_SEARCH_RE = r"https://sources\.debian\.org/api/search/.*"
_DETAIL_RE = r"https://sources\.debian\.org/api/src/.*"

_CURL_DETAIL: dict[str, Any] = {
    "package": "curl",
    "path": "curl",
    "pathl": [["curl", "/src/curl"]],
    "suite": "",
    "type": "package",
    "versions": [
        {"area": "main", "suites": ["forky", "sid"], "version": "8.22.0-1"},
        {"area": "main", "suites": ["trixie"], "version": "8.14.1-2+deb13u5"},
        {"area": "main", "suites": [], "version": "7.88.1-10+deb12u15"},
    ],
}


def _names_payload(exact: str | None, other: list[str]) -> dict[str, Any]:
    """Build a sources.debian.org search response for *exact* and *other*."""
    return {
        "query": exact or "",
        "results": {
            "exact": {"name": exact} if exact else None,
            "other": [{"name": name} for name in other],
        },
        "suite": "",
    }


def test_debian_name_tags_and_availability() -> None:
    p = DebianProvider()
    assert p.name == "debian"
    assert p.tags == ["web", "code", "developer", "packages"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_debian_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "debian" in registry
    assert registry["debian"].tags == ["web", "code", "developer", "packages"]


def test_debian_parse_names_puts_exact_first() -> None:
    from metasearchmcp.providers.debian import _parse_names

    assert _parse_names(_names_payload("curl", ["curlftpfs", "pycurl"])) == [
        "curl",
        "curlftpfs",
        "pycurl",
    ]


def test_debian_parse_names_without_exact_match() -> None:
    from metasearchmcp.providers.debian import _parse_names

    assert _parse_names(_names_payload(None, ["framework", "framework2"])) == [
        "framework",
        "framework2",
    ]


def test_debian_parse_names_deduplicates_and_skips_junk() -> None:
    from metasearchmcp.providers.debian import _parse_names

    payload = {
        "results": {
            "exact": {"name": "git"},
            "other": [{"name": "git"}, {"name": "  "}, {}, "junk", {"name": "git-lfs"}],
        }
    }
    assert _parse_names(payload) == ["git", "git-lfs"]


def test_debian_parse_names_malformed_payloads() -> None:
    from metasearchmcp.providers.debian import _parse_names

    assert _parse_names(None) == []
    assert _parse_names([]) == []
    assert _parse_names("nope") == []
    assert _parse_names({}) == []
    assert _parse_names({"results": "nope"}) == []
    assert _parse_names({"results": {"exact": "curl", "other": 5}}) == []


def test_debian_parse_versions_keeps_order_and_fields() -> None:
    from metasearchmcp.providers.debian import _parse_versions

    versions = _parse_versions(_CURL_DETAIL)
    assert [v["version"] for v in versions] == [
        "8.22.0-1",
        "8.14.1-2+deb13u5",
        "7.88.1-10+deb12u15",
    ]
    assert versions[0] == {
        "version": "8.22.0-1",
        "area": "main",
        "suites": ["forky", "sid"],
    }
    assert versions[2]["suites"] == []


def test_debian_parse_versions_odd_field_types() -> None:
    from metasearchmcp.providers.debian import _parse_versions

    payload = {
        "versions": [
            {"version": " 1.0 ", "area": "main", "suites": ["sid", 7, "", None]},
            {"version": "", "area": "main"},
            {"version": 5},
            "junk",
            {"version": "2.0", "area": None},
        ]
    }
    assert _parse_versions(payload) == [
        {"version": "1.0", "area": "main", "suites": ["sid"]},
        {"version": "2.0", "area": None, "suites": []},
    ]


def test_debian_parse_versions_malformed_payloads() -> None:
    from metasearchmcp.providers.debian import _parse_versions

    assert _parse_versions(None) == []
    assert _parse_versions({}) == []
    assert _parse_versions({"versions": "nope"}) == []
    assert _parse_versions({"versions": [1, 2]}) == []


def test_debian_fallback_term() -> None:
    from metasearchmcp.providers.debian import _fallback_term

    assert _fallback_term("web framework") == "framework"
    assert _fallback_term("a bbbb cc") == "bbbb"
    assert _fallback_term("curl") == ""
    assert _fallback_term("   ") == ""


def test_debian_snippet_formats_versions() -> None:
    from metasearchmcp.providers.debian import _parse_versions, _snippet

    history = _parse_versions(_CURL_DETAIL)
    assert _snippet(history) == (
        "8.22.0-1 in forky, sid | 8.14.1-2+deb13u5 in trixie | "
        "7.88.1-10+deb12u15 (no current suite)"
    )
    assert _snippet([]) == "Debian source package"


def test_debian_build_result_fields() -> None:
    p = DebianProvider()
    history = [
        {"version": "8.22.0-1", "area": "main", "suites": ["forky", "sid"]},
        {"version": "7.88.1-10+deb12u15", "area": "main", "suites": []},
    ]
    r = p._build_result("curl", "curl", history, total=42, rank=1)

    assert r.title == "curl"
    assert r.url == "https://sources.debian.org/src/curl/"
    assert r.source == "sources.debian.org"
    assert r.provider == "debian"
    assert r.rank == 1
    assert r.snippet == "8.22.0-1 in forky, sid | 7.88.1-10+deb12u15 (no current suite)"
    assert r.extra["name"] == "curl"
    assert r.extra["searched_term"] == "curl"
    assert r.extra["exact_match"] is True
    assert r.extra["latest_version"] == "8.22.0-1"
    assert r.extra["suites"] == ["forky", "sid"]
    assert r.extra["areas"] == ["main"]
    assert r.extra["versions"] == history
    assert r.extra["total_results"] == 42


def test_debian_build_result_without_history() -> None:
    p = DebianProvider()
    r = p._build_result("git-lfs", "web framework", None, total=1, rank=3)

    assert r.url == "https://sources.debian.org/src/git-lfs/"
    assert r.snippet == "Debian source package"
    assert r.rank == 3
    assert r.extra["exact_match"] is False
    assert r.extra["latest_version"] is None
    assert r.extra["suites"] == []
    assert r.extra["areas"] == []
    assert r.extra["versions"] == []


def test_debian_build_result_encodes_url_and_area() -> None:
    p = DebianProvider()
    history = [{"version": "1.0", "area": "contrib", "suites": ["sid"]}]
    r = p._build_result("g++", "g++", history, total=1, rank=1)

    assert r.url == "https://sources.debian.org/src/g%2B%2B/"
    assert r.extra["areas"] == ["contrib"]


async def test_debian_search_sends_expected_request(respx_mock) -> None:
    search = respx_mock.get(url__regex=_SEARCH_RE).mock(
        return_value=respx.MockResponse(200, json=_names_payload("curl", ["curlftpfs"]))
    )
    respx_mock.get(url__regex=_DETAIL_RE).mock(
        return_value=respx.MockResponse(200, json=_CURL_DETAIL)
    )

    result = await DebianProvider().search("  curl ", SearchParams(num_results=7))

    assert search.called
    assert str(search.calls[0].request.url) == (
        "https://sources.debian.org/api/search/curl/"
    )
    assert [r.title for r in result.results] == ["curl", "curlftpfs"]
    assert [r.rank for r in result.results] == [1, 2]
    assert result.results[0].snippet == (
        "8.22.0-1 in forky, sid | 8.14.1-2+deb13u5 in trixie | "
        "7.88.1-10+deb12u15 (no current suite)"
    )
    assert result.results[0].extra["total_results"] == 2
    assert result.results[0].extra["exact_match"] is True
    # Both hits are within the detail-lookup window, so both were enriched.
    assert len(respx_mock.calls) == 3


async def test_debian_search_caps_results_to_provider_limit(respx_mock) -> None:
    respx_mock.get(url__regex=_SEARCH_RE).mock(
        return_value=respx.MockResponse(
            200, json=_names_payload(None, [f"port{n}" for n in range(10)])
        )
    )
    respx_mock.get(url__regex=_DETAIL_RE).mock(
        return_value=respx.MockResponse(200, json=_CURL_DETAIL)
    )

    provider = DebianProvider()
    provider._max_results = 3
    result = await provider.search("port", SearchParams(num_results=50))

    assert len(result.results) == 3
    assert result.results[0].extra["total_results"] == 10
    # 1 search + 3 detail lookups.
    assert len(respx_mock.calls) == 4


async def test_debian_search_skips_detail_lookups_beyond_window(respx_mock) -> None:
    respx_mock.get(url__regex=_SEARCH_RE).mock(
        return_value=respx.MockResponse(
            200, json=_names_payload(None, [f"pkg{n}" for n in range(15)])
        )
    )
    detail_route = respx_mock.get(url__regex=_DETAIL_RE).mock(
        return_value=respx.MockResponse(200, json=_CURL_DETAIL)
    )

    provider = DebianProvider()
    provider._max_results = 15
    result = await provider.search("pkg", SearchParams(num_results=15))

    assert len(result.results) == 15
    assert len(detail_route.calls) == 10
    assert result.results[9].extra["latest_version"] == "8.22.0-1"
    assert result.results[10].snippet == "Debian source package"
    assert result.results[10].extra["versions"] == []


async def test_debian_search_tolerates_detail_failures(respx_mock) -> None:
    respx_mock.get(url__regex=_SEARCH_RE).mock(
        return_value=respx.MockResponse(200, json=_names_payload("curl", ["curlftpfs"]))
    )
    respx_mock.get(url__regex=_DETAIL_RE).mock(return_value=respx.MockResponse(500))

    result = await DebianProvider().search("curl", SearchParams())

    assert [r.title for r in result.results] == ["curl", "curlftpfs"]
    assert [r.snippet for r in result.results] == [
        "Debian source package",
        "Debian source package",
    ]


async def test_debian_search_retries_with_longest_word(respx_mock) -> None:
    search = respx_mock.get(url__regex=_SEARCH_RE).mock(
        side_effect=[
            respx.MockResponse(200, json=_names_payload(None, [])),
            respx.MockResponse(200, json=_names_payload("framework", [])),
        ]
    )
    respx_mock.get(url__regex=_DETAIL_RE).mock(
        return_value=respx.MockResponse(200, json=_CURL_DETAIL)
    )

    result = await DebianProvider().search("web framework", SearchParams())

    assert len(search.calls) == 2
    assert str(search.calls[0].request.url) == (
        "https://sources.debian.org/api/search/web%20framework/"
    )
    assert str(search.calls[1].request.url) == (
        "https://sources.debian.org/api/search/framework/"
    )
    assert [r.title for r in result.results] == ["framework"]
    assert result.results[0].extra["searched_term"] == "framework"
    assert result.results[0].extra["exact_match"] is True


async def test_debian_search_single_word_without_results(respx_mock) -> None:
    search = respx_mock.get(url__regex=_SEARCH_RE).mock(
        return_value=respx.MockResponse(200, json=_names_payload(None, []))
    )

    result = await DebianProvider().search("zzznotathing", SearchParams())

    assert result.results == []
    assert len(search.calls) == 1


async def test_debian_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(url__regex=_SEARCH_RE)

    result = await DebianProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_debian_search_raises_on_search_http_error(respx_mock) -> None:
    respx_mock.get(url__regex=_SEARCH_RE).mock(return_value=respx.MockResponse(503))

    with pytest.raises(httpx.HTTPStatusError):
        await DebianProvider().search("curl", SearchParams())


async def test_debian_search_handles_malformed_search_payload(respx_mock) -> None:
    respx_mock.get(url__regex=_SEARCH_RE).mock(
        return_value=respx.MockResponse(200, json={"results": "nope"})
    )

    result = await DebianProvider().search("curl", SearchParams())

    assert result.results == []
