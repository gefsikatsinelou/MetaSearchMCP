"""Unit tests for the Software Heritage archive origin search provider."""

from __future__ import annotations

import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.software_heritage import (
    SoftwareHeritageProvider,
    _host,
    _strings,
)

_SEARCH_URL = "https://archive.softwareheritage.org/api/1/origin/search"

_REPO_URL = (
    "https://github.com/sivakumarmanoharan/Principal-Component-Analysis-using-numpy"
)
_ARCHIVE_URL = (
    "https://archive.softwareheritage.org/browse/origin/?origin_url="
    "https%3A%2F%2Fgithub.com%2Fsivakumarmanoharan%2F"
    "Principal-Component-Analysis-using-numpy"
)

_RESPONSE: list[dict[str, object]] = [
    {
        "url": _REPO_URL,
        "visit_types": ["git"],
        "has_visits": True,
        "nb_visits": 52,
        "snapshot_id": "06aa59fa9a87b85f171bc1529d41a04c4bff18cd",
        "last_visit_date": "2026-08-08T18:40:11.549223+00:00",
        "last_eventful_visit_date": "2026-04-30T21:02:05.144649Z",
        "origin_visits_url": (
            "https://archive.softwareheritage.org/api/1/origin/"
            "https://github.com/sivakumarmanoharan/Principal-Component-Analysis-using-numpy"
            "/visits/"
        ),
    },
    {
        "url": "https://gitlab.com/example/project/",
        "visit_types": ["git", "svn"],
        "has_visits": False,
        "nb_visits": 0,
        "snapshot_id": None,
        "last_visit_date": None,
    },
]


def _provider() -> SoftwareHeritageProvider:
    return SoftwareHeritageProvider()


def test_name_tags_and_description() -> None:
    p = _provider()
    assert p.name == "software_heritage"
    assert p.tags == ["code", "developer", "repos", "archive"]
    assert "No API key required" in p.description


def test_parse_builds_results_in_api_order() -> None:
    result = _provider()._parse(_RESPONSE)

    assert [r.title for r in result.results] == [
        "github.com/sivakumarmanoharan/Principal-Component-Analysis-using-numpy",
        "gitlab.com/example/project",
    ]


def test_parse_maps_an_archived_origin() -> None:
    first = _provider()._parse(_RESPONSE, total=85010).results[0]

    assert first.url == _ARCHIVE_URL
    assert first.source == "archive.softwareheritage.org"
    assert first.provider == "software_heritage"
    assert first.rank == 1
    assert first.published_date == "2026-08-08"
    assert first.snippet == (
        "github.com | Archived via git | 52 visits | last visit 2026-08-08"
    )
    assert first.extra == {
        "repository_url": _REPO_URL,
        "host": "github.com",
        "archive_url": _ARCHIVE_URL,
        "visit_types": ["git"],
        "has_visits": True,
        "nb_visits": 52,
        "snapshot_id": "06aa59fa9a87b85f171bc1529d41a04c4bff18cd",
        "last_visit_date": "2026-08-08T18:40:11.549223+00:00",
        "total_results": 85010,
    }


def test_parse_marks_origins_without_a_snapshot() -> None:
    second = _provider()._parse(_RESPONSE).results[1]

    assert second.rank == 2
    assert second.published_date is None
    assert second.snippet == (
        "gitlab.com | Archived via git, svn | no snapshot captured"
    )
    assert second.extra["has_visits"] is False
    assert second.extra["nb_visits"] == 0
    assert second.extra["snapshot_id"] is None
    assert second.extra["last_visit_date"] is None
    assert second.extra["total_results"] is None


def test_parse_skips_malformed_entries() -> None:
    payload: list[object] = [
        "junk",
        {},
        {"url": "   "},
        {"url": 42},
        {"url": "https://bitbucket.org/example/repo"},
    ]

    results = _provider()._parse(payload).results

    assert len(results) == 1
    assert results[0].title == "bitbucket.org/example/repo"


def test_parse_malformed_payloads() -> None:
    p = _provider()
    assert p._parse(None).results == []
    assert p._parse({}).results == []
    assert p._parse("junk").results == []
    assert p._parse({"url": "https://example.com"}).results == []


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse(_RESPONSE, limit=1).results) == 1
    assert len(p._parse(_RESPONSE, 2).results) == 2


def test_title_strips_the_scheme_and_trailing_slash() -> None:
    p = _provider()
    assert p._title("https://github.com/owner/repo/") == "github.com/owner/repo"
    assert p._title("https://github.com") == "github.com"
    assert p._title("") == ""
    assert p._title("git://example.com/repo") == "example.com/repo"


def test_archive_url_encodes_the_origin() -> None:
    assert _provider()._archive_url(_REPO_URL) == _ARCHIVE_URL


def test_string_helpers_ignore_invalid_values() -> None:
    assert _strings(["git", "", "  hg ", 7]) == ["git", "hg"]
    assert _strings("git") == []
    assert _strings(None) == []
    assert _host("https://github.com/owner/repo") == "github.com"
    assert _host("not a url") == ""


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "software_heritage" in registry
    assert registry["software_heritage"].tags == [
        "code",
        "developer",
        "repos",
        "archive",
    ]


@pytest.mark.asyncio
async def test_search_queries_the_json_endpoint(respx_mock) -> None:
    route = respx_mock.get(f"{_SEARCH_URL}/numpy/").mock(
        return_value=respx.MockResponse(
            200,
            json=_RESPONSE,
            headers={"X-Total-Count": "85010"},
        )
    )

    p = _provider()
    result = await p.search("numpy", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].extra["total_results"] == 85010
    assert route.called
    call = respx_mock.calls[0]
    assert call.request.url.params["limit"] == "5"


@pytest.mark.asyncio
async def test_search_encodes_reserved_characters_in_the_path(respx_mock) -> None:
    route = respx_mock.get(f"{_SEARCH_URL}/github.com%2Ftensorflow/").mock(
        return_value=respx.MockResponse(200, json=[])
    )

    p = _provider()
    result = await p.search("github.com/tensorflow", SearchParams(num_results=5))

    assert result.results == []
    assert route.called


@pytest.mark.asyncio
async def test_search_returns_empty_on_404(respx_mock) -> None:
    respx_mock.get(f"{_SEARCH_URL}/zzzqqq/").mock(
        return_value=respx.MockResponse(404, json={"error": "not found"})
    )

    p = _provider()
    result = await p.search("zzzqqq", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_search_handles_an_empty_list(respx_mock) -> None:
    respx_mock.get(f"{_SEARCH_URL}/zzzqqq/").mock(
        return_value=respx.MockResponse(200, json=[])
    )

    p = _provider()
    result = await p.search("zzzqqq", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_search_skips_blank_query(respx_mock) -> None:
    route = respx_mock.get(url__regex=r".*/origin/search/.*")

    p = _provider()
    result = await p.search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_respects_provider_max_results(respx_mock) -> None:
    payload = [{"url": f"https://github.com/example/repo-{n}"} for n in range(40)]
    respx_mock.get(f"{_SEARCH_URL}/repo/").mock(
        return_value=respx.MockResponse(200, json=payload)
    )

    p = _provider()
    result = await p.search("repo", SearchParams(num_results=50))

    assert len(result.results) == p._max_results
    assert result.results[-1].rank == p._max_results
