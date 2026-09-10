"""Unit tests for the Artifact Hub package search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.artifacthub import ArtifactHubProvider

_SAMPLE_RESPONSE: dict[str, list[dict[str, object]]] = {
    "packages": [
        {
            "package_id": "0602c8d2-b17d-432f-89f0-95000f3057a2",
            "name": "redis",
            "stars": 509,
            "description": ("Redis(R) is an open source, advanced key-value store."),
            "version": "28.0.15",
            "app_version": "8.10.1",
            "license": "Apache-2.0",
            "deprecated": False,
            "ts": 1788486876,
            "repository": {
                "url": "https://charts.bitnami.com/bitnami",
                "kind": 0,
                "name": "bitnami",
                "display_name": "Bitnami",
                "official": False,
                "verified_publisher": True,
            },
        },
        {
            "name": "strimzi-kafka-operator",
            "stars": 12,
            "description": "Kafka Operator for Kubernetes",
            "version": "0.44.0",
            "ts": 0,
            "repository": {
                "kind": 3,
                "name": "community-operators",
                "display_name": "",
                "official": True,
            },
        },
        {
            # No display name -> falls back to repository name; odd kind -> search URL.
            "name": "weird-pkg",
            "description": "",
            "repository": {"kind": 999, "name": "some-repo"},
        },
        {
            # Missing name -> skipped.
            "description": "ghost",
            "repository": {"kind": 0, "name": "bitnami"},
        },
        "junk",
        None,
    ]
}

_EMPTY_RESPONSE: dict[str, list[object]] = {"packages": []}


def _provider() -> ArtifactHubProvider:
    return ArtifactHubProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "artifacthub"
    assert p.tags == ["web", "code", "developer", "kubernetes", "packages"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 3
    r = result.results[0]
    assert r.title == "redis"
    assert r.url == "https://artifacthub.io/packages/helm/bitnami/redis"
    assert "advanced key-value store" in r.snippet
    assert "v28.0.15" in r.snippet
    assert "Stars: 509" in r.snippet
    assert "Repo: Bitnami" in r.snippet
    assert r.source == "artifacthub.io"
    assert r.provider == "artifacthub"
    assert r.rank == 1
    assert r.published_date == "2026-09-04"
    assert r.extra["package_name"] == "redis"
    assert r.extra["version"] == "28.0.15"
    assert r.extra["app_version"] == "8.10.1"
    assert r.extra["stars"] == 509
    assert r.extra["license"] == "Apache-2.0"
    assert r.extra["repository"] == "bitnami"
    assert r.extra["repository_kind"] == 0
    assert r.extra["verified_publisher"] is True
    assert r.extra["deprecated"] is False


def test_parse_second_item_repo_and_zero_ts() -> None:
    r = _provider()._parse(_SAMPLE_RESPONSE).results[1]
    assert r.url == (
        "https://artifacthub.io/packages/olm/community-operators/strimzi-kafka-operator"
    )
    # Blank display name falls back to the repository name.
    assert "Repo: community-operators" in r.snippet
    # Non-positive timestamp -> no published date.
    assert r.published_date is None
    assert r.extra["repository_display_name"] == "community-operators"
    assert r.extra["official"] is True
    assert r.extra["license"] == ""


def test_parse_unknown_kind_falls_back_to_search_url() -> None:
    r = _provider()._parse(_SAMPLE_RESPONSE).results[2]
    assert r.url == "https://artifacthub.io/packages/search?ts_query_web=weird-pkg"
    assert r.extra["repository_kind"] == 999
    # Blank description and no version -> snippet only carries the repo.
    assert r.snippet == "Repo: some-repo"


def test_parse_skips_nameless_and_non_dict_items() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert len(result.results) == 3
    assert all(r.title for r in result.results)


def test_parse_limit_and_empty() -> None:
    p = _provider()
    assert len(p._parse(_SAMPLE_RESPONSE, limit=1).results) == 1
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse("junk").results == []  # type: ignore[arg-type]
    assert p._parse(None).results == []  # type: ignore[arg-type]
    assert p._parse({}).results == []  # type: ignore[arg-type]


def test_parse_accepts_top_level_list() -> None:
    p = _provider()
    result = p._parse(_SAMPLE_RESPONSE["packages"])
    assert len(result.results) == 3


def test_parse_snippet_capped_at_shared_limit() -> None:
    from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH

    long_description = "x" * (MAX_SNIPPET_LENGTH + 200)
    result = _provider()._parse(
        {
            "packages": [
                {
                    "name": "long",
                    "description": long_description,
                    "repository": {"kind": 0, "name": "bitnami"},
                }
            ]
        }
    )
    assert len(result.results[0].snippet) == MAX_SNIPPET_LENGTH


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_query(respx_mock) -> None:
    import respx

    respx_mock.get("https://artifacthub.io/api/v1/packages/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("redis", SearchParams(num_results=5))

    assert len(result.results) == 3
    request = respx_mock.calls.last.request
    assert request.url.params["ts_query_web"] == "redis"
    assert request.url.params["limit"] == "5"


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://artifacthub.io/api/v1/packages/search").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("no-such-package-xyz", SearchParams(num_results=5))
    assert result.results == []
