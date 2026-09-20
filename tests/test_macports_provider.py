"""Unit tests for the MacPorts package search provider."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.macports import MacPortsProvider

_ENDPOINT = "https://ports.macports.org/api/v1/ports/"

_GIT: dict[str, Any] = {
    "name": "git",
    "portdir": "devel/git",
    "version": "2.55.0",
    "license": "GPL-2 and LGPL-2.1+",
    "platforms": "darwin",
    "epoch": 0,
    "replaced_by": None,
    "homepage": "https://git-scm.com/",
    "description": "A fast version control system",
    "long_description": "Git is a fast, scalable, distributed version control system.",
    "active": True,
    "categories": ["devel"],
    "maintainers": [
        {"name": "ciserlohn", "github": "ci42", "ports_count": 34},
        {"name": "herby.gillot", "github": "herbygillot", "ports_count": 1118},
    ],
    "variants": ["universal", "pcre", "doc"],
    "dependencies": [
        {"type": "build", "ports": ["clang-18", "gettext"]},
        {"type": "lib", "ports": ["expat", "libiconv", "zlib"]},
    ],
}

# Minimal record: only a name and a ports-tree directory.
_BARE: dict[str, Any] = {"name": "bareport", "portdir": "misc/bareport"}

# Inactive port that was replaced; no description and no categories.
_REPLACED: dict[str, Any] = {
    "name": "old-port",
    "portdir": "devel/old-port",
    "version": "1.0",
    "active": False,
    "replaced_by": "new-port",
    "categories": ["devel"],
    "maintainers": [{"name": "someone"}],
    "epoch": 0,
}

# Hand-written record with unusual field types.
_ODD: dict[str, Any] = {
    "name": "odd-port",
    "portdir": "textproc/odd-port",
    "description": "Odd   port\nwith spaces",
    "categories": "textproc",
    "maintainers": ["solo", {"github": "gh-only"}, {"name": "  "}, 7],
    "variants": [1, "x", ""],
    "epoch": True,
    "active": "yes",
    "dependencies": [{"type": "lib", "ports": ["a", "b"]}, "junk", {"type": "build"}],
}


def _envelope(entries: list[Any], count: object = 54) -> dict[str, Any]:
    """Wrap *entries* in a MacPorts paginated response envelope."""
    return {"count": count, "next": None, "previous": None, "results": entries}


def test_macports_name_tags_and_availability() -> None:
    p = MacPortsProvider()
    assert p.name == "macports"
    assert p.tags == ["web", "code", "developer", "packages"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_macports_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "macports" in registry
    assert registry["macports"].tags == ["web", "code", "developer", "packages"]


def test_macports_parse_port_record() -> None:
    p = MacPortsProvider()
    result = p._parse(_envelope([_GIT]), limit=5)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "git"
    assert r.url == "https://ports.macports.org/port/git/"
    assert r.source == "ports.macports.org"
    assert r.provider == "macports"
    assert r.rank == 1
    assert r.snippet == (
        "A fast version control system | v2.55.0 | GPL-2 and LGPL-2.1+ | devel | "
        "by ciserlohn, herby.gillot"
    )
    assert r.extra["portdir"] == "devel/git"
    assert r.extra["version"] == "2.55.0"
    assert r.extra["license"] == "GPL-2 and LGPL-2.1+"
    assert r.extra["platforms"] == "darwin"
    assert r.extra["epoch"] == 0
    assert r.extra["categories"] == ["devel"]
    assert r.extra["maintainers"] == ["ciserlohn", "herby.gillot"]
    assert r.extra["variants"] == ["universal", "pcre", "doc"]
    assert r.extra["dependency_count"] == 5
    assert r.extra["active"] is True
    assert r.extra["replaced_by"] is None
    assert r.extra["homepage"] == "https://git-scm.com/"
    assert r.extra["long_description"] == (
        "Git is a fast, scalable, distributed version control system."
    )
    assert r.extra["total_results"] == 54


def test_macports_parse_bare_record_falls_back_to_portdir() -> None:
    p = MacPortsProvider()
    r = p._parse(_envelope([_BARE], count=None)).results[0]

    assert r.title == "bareport"
    assert r.url == "https://ports.macports.org/port/bareport/"
    assert r.snippet == "misc/bareport"
    assert r.extra["version"] is None
    assert r.extra["categories"] == []
    assert r.extra["maintainers"] == []
    assert r.extra["dependency_count"] == 0
    assert r.extra["active"] is None
    assert r.extra["total_results"] is None


def test_macports_parse_replaced_port() -> None:
    p = MacPortsProvider()
    r = p._parse(_envelope([_REPLACED])).results[0]

    assert r.snippet == "v1.0 | devel | by someone | replaced by new-port"
    assert r.extra["active"] is False
    assert r.extra["replaced_by"] == "new-port"


def test_macports_parse_odd_field_types() -> None:
    p = MacPortsProvider()
    r = p._parse(_envelope([_ODD])).results[0]

    assert r.snippet == "Odd port with spaces | by solo, gh-only"
    assert r.extra["categories"] == []
    assert r.extra["maintainers"] == ["solo", "gh-only"]
    assert r.extra["variants"] == ["x"]
    assert r.extra["epoch"] is None
    assert r.extra["active"] is None
    assert r.extra["dependency_count"] == 2
    assert r.extra["description"] == "Odd port with spaces"


def test_macports_snippet_truncates_long_description() -> None:
    p = MacPortsProvider()
    record = {"name": "long", "description": "word " * 100}
    r = p._parse(_envelope([record])).results[0]

    assert r.snippet.endswith("…")
    assert len(r.snippet) <= 200


def test_macports_snippet_marks_long_lists() -> None:
    p = MacPortsProvider()
    record = {
        "name": "many",
        "categories": ["a", "b", "c", "d"],
        "maintainers": [{"name": n} for n in ("m1", "m2", "m3", "m4")],
    }
    r = p._parse(_envelope([record])).results[0]

    assert r.extra["categories"] == ["a", "b", "c", "d"]
    assert r.extra["maintainers"] == ["m1", "m2", "m3", "m4"]
    assert r.snippet == "a, b, c | by m1, m2, m3 et al."


def test_macports_parse_skips_records_without_name() -> None:
    p = MacPortsProvider()
    payload = _envelope([{}, {"portdir": "devel/no-name"}, "nope", _BARE])
    results = p._parse(payload).results

    assert [r.title for r in results] == ["bareport"]
    assert results[0].rank == 1


def test_macports_parse_deduplicates_names() -> None:
    p = MacPortsProvider()
    first = dict(_GIT, version="2.55.0")
    second = dict(_GIT, version="2.54.0")
    payload = _envelope([first, second, _BARE])

    results = p._parse(payload).results

    assert [r.title for r in results] == ["git", "bareport"]
    assert results[0].extra["version"] == "2.55.0"
    assert [r.rank for r in results] == [1, 2]


def test_macports_parse_respects_limit() -> None:
    p = MacPortsProvider()
    entries = [dict(_BARE, name=f"port{n}") for n in range(3)]

    assert len(p._parse(_envelope(entries), limit=2).results) == 2
    assert len(p._parse(_envelope(entries)).results) == 3


def test_macports_parse_empty_and_malformed() -> None:
    p = MacPortsProvider()
    assert p._parse(_envelope([])).results == []
    assert p._parse({}).results == []
    assert p._parse({"results": "nope"}).results == []
    assert p._parse({"results": [1, 2, 3]}).results == []
    assert p._parse([1, 2, 3]).results == []
    assert p._parse(None).results == []
    assert p._parse({"results": [{"portdir": "devel/x"}]}).results == []


def test_macports_helpers() -> None:
    from metasearchmcp.providers.macports import (
        _clean,
        _dependency_count,
        _int,
        _maintainers,
        _str_list,
        _truncate,
    )

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _clean(5) == ""

    assert _int(3) == 3
    assert _int(True) is None
    assert _int("3") is None
    assert _int(None) is None

    assert _str_list([" a ", "", 5, None]) == ["a"]
    assert _str_list("a") == []
    assert _str_list(None) == []

    assert _maintainers([{"name": "n"}, {"github": "g"}, "s", 5, {}]) == ["n", "g", "s"]
    assert _maintainers({"name": "n"}) == []
    assert _maintainers(None) == []

    assert _dependency_count([{"ports": ["a", "b"]}, {"ports": "x"}, "junk"]) == 2
    assert _dependency_count(None) == 0

    assert _truncate("short", 10) == "short"
    assert _truncate("a" * 10, 5) == "aaaa…"


async def test_macports_search_sends_expected_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope([_GIT, _BARE]))
    )

    result = await MacPortsProvider().search("git", SearchParams(num_results=7))

    assert route.called
    params = route.calls[0].request.url.params
    assert params["search"] == "git"
    assert params["per_page"] == "7"
    assert params["page"] == "1"
    assert len(respx_mock.calls) == 1
    assert [r.title for r in result.results] == ["git", "bareport"]


async def test_macports_search_caps_results_to_provider_limit(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(
            200,
            json=_envelope([dict(_BARE, name=f"port{n}") for n in range(10)]),
        )
    )

    provider = MacPortsProvider()
    provider._max_results = 3
    result = await provider.search("port", SearchParams(num_results=50))

    assert len(respx_mock.calls) == 1
    assert len(result.results) == 3
    assert respx_mock.calls[0].request.url.params["per_page"] == "3"


async def test_macports_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT)

    result = await MacPortsProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_macports_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(503))

    with pytest.raises(httpx.HTTPStatusError):
        await MacPortsProvider().search("git", SearchParams())
