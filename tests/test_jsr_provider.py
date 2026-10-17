"""Unit tests for the JSR (@jsr) package search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.jsr import JsrProvider

_SAMPLE_RESPONSE: dict[str, object] = {
    "total": 3,
    "items": [
        {
            "scope": "oak",
            "name": "oak",
            "description": (
                "A middleware framework for handling HTTP with Deno, "
                "Node.js, Bun and Cloudflare Workers"
            ),
            "githubRepository": {"owner": "oakserver", "name": "oak"},
            "runtimeCompat": {
                "browser": False,
                "deno": True,
                "node": True,
                "workerd": True,
                "bun": True,
            },
            "updatedAt": "2024-03-01T04:23:01.583567Z",
            "createdAt": "2021-04-28T15:00:00.000000Z",
            "versionCount": 32,
            "dependencyCount": 0,
            "dependentCount": 145,
            "score": 94,
            "latestVersion": "0.17.1",
            "isArchived": False,
        },
        {
            "scope": "std",
            "name": "assert",
            "description": "",
            "githubRepository": None,
            "runtimeCompat": {},
            "versionCount": 12,
            "latestVersion": "1.0.0",
            "score": 99,
            "isArchived": True,
        },
        # Missing name -> skipped.
        {"scope": "lonely", "name": ""},
        "junk",
        None,
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"items": [], "total": 0}


def _provider() -> JsrProvider:
    return JsrProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "jsr"
    assert p.tags == ["web", "code", "developer", "packages"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "@oak/oak"
    assert r.url == "https://jsr.io/@oak/oak"
    assert "A middleware framework" in r.snippet
    assert "v0.17.1" in r.snippet
    assert "score 94" in r.snippet
    assert "32 versions" in r.snippet
    assert "145 dependents" in r.snippet
    assert "runs on bun, deno, node, workerd" in r.snippet
    assert r.source == "jsr.io"
    assert r.provider == "jsr"
    assert r.rank == 1
    assert r.extra["package"] == "@oak/oak"
    assert r.extra["scope"] == "oak"
    assert r.extra["name"] == "oak"
    assert r.extra["latest_version"] == "0.17.1"
    assert r.extra["version_count"] == 32
    assert r.extra["dependent_count"] == 145
    assert r.extra["score"] == 94
    assert r.extra["runtime_compat"] == ["bun", "deno", "node", "workerd"]
    assert r.extra["github_repo"] == "oakserver/oak"
    assert r.extra["is_archived"] is False
    assert r.extra["created_at"] == "2021-04-28T15:00:00.000000Z"


def test_parse_blank_description_and_archived() -> None:
    r = _provider()._parse(_SAMPLE_RESPONSE).results[1]
    assert r.title == "@std/assert"
    assert r.url == "https://jsr.io/@std/assert"
    # Blank description -> snippet carries only the populated fields.
    assert r.snippet == "v1.0.0 | score 99 | 12 versions"
    # No linked repository -> empty slug rather than a crash.
    assert r.extra["github_repo"] == ""
    assert r.extra["is_archived"] is True
    assert r.rank == 2


def test_parse_skips_nameless_and_non_dict_items() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert len(result.results) == 2
    assert all(r.title.startswith("@") for r in result.results)


def test_parse_limit_and_empty() -> None:
    p = _provider()
    assert len(p._parse(_SAMPLE_RESPONSE, limit=1).results) == 1
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []  # type: ignore[arg-type]
    assert p._parse([]).results == []  # type: ignore[arg-type]
    assert p._parse("junk").results == []  # type: ignore[arg-type]
    assert p._parse(None).results == []  # type: ignore[arg-type]


def test_parse_snippet_capped_at_shared_limit() -> None:
    from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH

    long_description = "x" * (MAX_SNIPPET_LENGTH + 200)
    result = _provider()._parse(
        {
            "items": [
                {
                    "scope": "vendor",
                    "name": "long",
                    "description": long_description,
                }
            ]
        }
    )
    assert len(result.results[0].snippet) == MAX_SNIPPET_LENGTH


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_query_and_limit(respx_mock) -> None:
    import respx

    respx_mock.get("https://jsr.io/api/packages").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("oak", SearchParams(num_results=5))

    assert len(result.results) == 2
    request = respx_mock.calls.last.request
    assert request.url.params["query"] == "oak"
    assert request.url.params["limit"] == "5"


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://jsr.io/api/packages").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("no-such-package-xyz", SearchParams(num_results=5))
    assert result.results == []
