"""Unit tests for the Repology cross-distribution package search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.repology import RepologyProvider

_SAMPLE_RESPONSE: dict[str, object] = {
    "curl": [
        {
            "repo": "alpine_3_19",
            "subrepo": "main",
            "srcname": "curl",
            "visiblename": "curl",
            "version": "8.5.0-r0",
            "status": "newest",
            "summary": "Command line tool for transferring data with URLs",
            "maintainers": ["maintainer@alpinelinux.org"],
            "licenses": ["curl"],
            "categories": ["networking"],
        },
        {
            "repo": "debian_13",
            "srcname": "curl",
            "visiblename": "curl",
            "version": "8.5.0-1",
            "status": "newest",
            "summary": "Command line tool for transferring data with URLs",
            "maintainers": [],
            "licenses": ["curl"],
            "categories": ["web"],
        },
        {
            "repo": "nix_stable_24_05",
            "srcname": "curl",
            "visiblename": "curl",
            "version": "7.88.1",
            "status": "legacy",
            "summary": "Command line tool for transferring data with URLs",
            "maintainers": [],
            "licenses": [],
            "categories": [],
        },
    ],
    "curlyq": [
        {
            "repo": "aur",
            "srcname": "curlyq",
            "visiblename": "curlyq",
            "version": "0.5",
            "status": "unique",
            "summary": "",
        },
    ],
    # Non-list payload -> skipped.
    "broken": "junk",
    # Entries that are not dicts -> skipped, project dropped.
    "noentry": ["junk", None],
    "": [
        {"repo": "x", "version": "1", "status": "unique"},
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {}


def _provider() -> RepologyProvider:
    return RepologyProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "repology"
    assert p.tags == ["web", "code", "developer", "packages"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    # "curl" (3 repos) ranks before "curlyq" (1 repo); broken/empty dropped.
    assert [r.title for r in result.results] == ["curl", "curlyq"]
    r = result.results[0]
    assert r.title == "curl"
    assert r.url == "https://repology.org/project/curl/versions"
    assert "Command line tool" in r.snippet
    assert "latest 8.5.0-r0" in r.snippet
    assert "in 3 repositories" in r.snippet
    assert "3 distinct versions" in r.snippet
    assert "status: legacy, newest" in r.snippet
    assert r.source == "repology.org"
    assert r.provider == "repology"
    assert r.rank == 1
    assert r.extra["project"] == "curl"
    assert r.extra["latest_version"] == "8.5.0-r0"
    assert r.extra["repo_count"] == 3
    assert r.extra["versions"] == ["7.88.1", "8.5.0-1", "8.5.0-r0"]
    assert r.extra["statuses"] == ["legacy", "newest"]
    assert r.extra["licenses"] == ["curl"]
    assert r.extra["maintainers"] == ["maintainer@alpinelinux.org"]
    assert r.extra["repositories"][0]["repo"] == "alpine_3_19"
    assert r.extra["repositories"][0]["version"] == "8.5.0-r0"


def test_parse_sparse_project() -> None:
    r = _provider()._parse(_SAMPLE_RESPONSE).results[1]
    assert r.title == "curlyq"
    assert r.url == "https://repology.org/project/curlyq/versions"
    # No summary -> snippet carries only version/repo/status info.
    assert r.snippet == "latest 0.5 | in 1 repositories | status: unique"
    assert r.extra["licenses"] == []
    assert r.rank == 2


def test_parse_drops_malformed_entries() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    titles = {r.title for r in result.results}
    assert "broken" not in titles
    assert "noentry" not in titles
    assert "" not in titles


def test_parse_empty_and_junk() -> None:
    p = _provider()
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []
    assert p._parse([]).results == []  # type: ignore[arg-type]
    assert p._parse("junk").results == []  # type: ignore[arg-type]
    assert p._parse(None).results == []  # type: ignore[arg-type]


def test_parse_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1
    assert result.results[0].title == "curl"


def test_parse_snippet_capped_at_shared_limit() -> None:
    from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH

    long_summary = "x" * (MAX_SNIPPET_LENGTH + 200)
    result = _provider()._parse(
        {
            "proj": [
                {
                    "repo": "a",
                    "version": "1",
                    "status": "newest",
                    "summary": long_summary,
                },
            ]
        }
    )
    assert len(result.results[0].snippet) == MAX_SNIPPET_LENGTH


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_search_param(respx_mock) -> None:
    import respx

    respx_mock.get("https://repology.org/api/v1/projects/").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("curl", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["curl", "curlyq"]
    request = respx_mock.calls.last.request
    assert request.url.params["search"] == "curl"


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://repology.org/api/v1/projects/").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("no-such-project-xyz", SearchParams(num_results=5))
    assert result.results == []
