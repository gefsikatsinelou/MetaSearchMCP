"""Unit tests for the Sourcegraph code search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.providers.sourcegraph import SourcegraphProvider

_SAMPLE_SSE = (
    "event: filters\n"
    'data: [{"value":"archived:yes","label":"Include archived repos"}]\n'
    "\n"
    "event: matches\n"
    "data: ["
    '{"type":"content","path":"fastapi/clib.py",'
    '"repository":"github.com/Oxicid/UniV","repoStars":140,'
    '"commit":"3a0a841db4007aa3963eda206810149c67676b90",'
    '"lineMatches":[{"line":"EXPECTED_FASTAPI_VERSION = 4","lineNumber":19},'
    '{"line":"class FastAPI:","lineNumber":21}],"language":"Python"},'
    '{"type":"content","path":"README.md",'
    '"repository":"github.com/example/flask-app","repoStars":0,'
    '"commit":"abc123","lineMatches":[],"language":"Markdown"},'
    '{"type":"path","path":"some/dir","repository":"github.com/example/other"}'
    "]\n"
    "\n"
    "event: progress\n"
    'data: {"done":true,"matchCount":2}\n'
    "\n"
    "event: done\n"
    "data: {}\n"
    "\n"
)

_EMPTY_SSE = """event: progress
data: {"done":true,"matchCount":0}

event: done
data: {}
"""


def test_parse_sse_events_basic():
    events = SourcegraphProvider._parse_sse_events(_SAMPLE_SSE)
    names = [name for name, _ in events]
    assert names == ["filters", "matches", "progress", "done"]
    matches = next(data for name, data in events if name == "matches")
    assert isinstance(matches, list)
    assert len(matches) == 3


def test_parse_sse_events_plain_text_payload():
    # data lines that are not JSON should be kept as strings.
    events = SourcegraphProvider._parse_sse_events("event: x\ndata: hello\n\n")
    assert events == [("x", "hello")]


def test_parse_basic():
    p = SourcegraphProvider()
    result = p._parse(_SAMPLE_SSE)

    assert len(result.results) == 3
    r = result.results[0]
    assert r.title == "github.com/Oxicid/UniV · fastapi/clib.py"
    assert r.url == (
        "https://sourcegraph.com/github.com/Oxicid/UniV"
        "@3a0a841db4007aa3963eda206810149c67676b90/-/blob/fastapi/clib.py"
    )
    assert r.provider == "sourcegraph"
    assert r.source == "sourcegraph.com"
    assert r.rank == 1
    assert r.extra["repo_stars"] == 140
    assert r.extra["language"] == "Python"
    assert r.extra["matching_lines"] == [
        "EXPECTED_FASTAPI_VERSION = 4",
        "class FastAPI:",
    ]
    assert "Language: Python" in r.snippet
    assert "Stars: 140" in r.snippet


def test_parse_keeps_content_and_path_matches():
    p = SourcegraphProvider()
    result = p._parse(_SAMPLE_SSE)
    # Two "content" matches plus one "path" match are all kept.
    assert len(result.results) == 3
    match_types = [r.extra["match_type"] for r in result.results]
    assert match_types.count("content") == 2
    assert match_types.count("path") == 1
    # A path match with no code lines still exposes its path in the snippet.
    path_result = next(r for r in result.results if r.extra["match_type"] == "path")
    assert "Path: some/dir" in path_result.snippet


def test_parse_empty():
    p = SourcegraphProvider()
    result = p._parse(_EMPTY_SSE)
    assert result.results == []


def test_parse_no_matches_event():
    p = SourcegraphProvider()
    result = p._parse("event: done\ndata: {}\n\n")
    assert result.results == []


def test_match_url_with_and_without_commit():
    assert (
        SourcegraphProvider._match_url(
            {"repository": "github.com/a/b", "commit": "deadbeef", "path": "x.py"}
        )
        == "https://sourcegraph.com/github.com/a/b@deadbeef/-/blob/x.py"
    )
    assert (
        SourcegraphProvider._match_url(
            {"repository": "github.com/a/b", "commit": "", "path": "x.py"}
        )
        == "https://sourcegraph.com/github.com/a/b/-/blob/x.py"
    )


def test_is_available():
    """Keyless provider is always available."""
    assert SourcegraphProvider().is_available() is True


@pytest.mark.asyncio
async def test_search_builds_query(respx_mock):
    """The search method hits the streaming endpoint and parses the response."""
    import respx

    respx_mock.get(
        "https://sourcegraph.com/.api/search/stream",
        params={"q": "fastapi", "display": "5"},
    ).mock(
        return_value=respx.MockResponse(
            200,
            text=_SAMPLE_SSE,
            headers={"Content-Type": "text/event-stream"},
        ),
    )

    from metasearchmcp.contracts import SearchParams

    p = SourcegraphProvider()
    result = await p.search("fastapi", SearchParams(num_results=5))

    assert len(result.results) == 3
    assert result.results[0].provider == "sourcegraph"
