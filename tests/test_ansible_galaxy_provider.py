"""Unit tests for the Ansible Galaxy collection search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.ansible_galaxy import AnsibleGalaxyProvider
from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH

_SAMPLE_RESPONSE: dict[str, object] = {
    "meta": {"count": 4},
    "data": [
        {
            "collection_version": {
                "namespace": "community",
                "name": "general",
                "version": "9.0.0",
                "description": "A collection of community-maintained modules",
                "requires_ansible": ">=2.15.0",
                "tags": [{"name": "community"}, {"name": "utility"}],
                "dependencies": {"community.library_inventory_filtering_v1": ">=1.0.0"},
            },
            "repository": {"pulp_last_updated": "2024-05-02T10:00:00.123456Z"},
            "is_highest": True,
            "is_deprecated": False,
            "is_signed": True,
        },
        # Lower version of the same collection -> collapsed away.
        {
            "collection_version": {
                "namespace": "community",
                "name": "general",
                "version": "8.6.0",
                "description": "older release",
            },
            "is_highest": False,
        },
        {
            "collection_version": {
                "namespace": "ansible",
                "name": "posix",
                "version": "1.5.4",
                "description": "",
                "requires_ansible": ">=2.9",
                "tags": [],
                "dependencies": {},
            },
            "repository": {},
            "is_highest": True,
            "is_deprecated": True,
            "is_signed": False,
        },
        # Missing name -> skipped.
        {
            "collection_version": {"namespace": "lonely", "name": ""},
            "is_highest": True,
        },
        "junk",
        None,
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"meta": {"count": 0}, "data": []}


def _provider() -> AnsibleGalaxyProvider:
    return AnsibleGalaxyProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "ansible_galaxy"
    assert p.tags == ["web", "code", "developer", "packages"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=10)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "community.general"
    assert r.url == "https://galaxy.ansible.com/ui/repo/published/community/general/"
    assert "community-maintained modules" in r.snippet
    assert "v9.0.0" in r.snippet
    assert "requires Ansible >=2.15.0" in r.snippet
    assert "tags: community, utility" in r.snippet
    assert "DEPRECATED" not in r.snippet
    assert r.source == "galaxy.ansible.com"
    assert r.provider == "ansible_galaxy"
    assert r.rank == 1
    assert r.published_date == "2024-05-02"
    assert r.extra["namespace"] == "community"
    assert r.extra["name"] == "general"
    assert r.extra["version"] == "9.0.0"
    assert r.extra["requires_ansible"] == ">=2.15.0"
    assert r.extra["tags"] == ["community", "utility"]
    assert r.extra["dependencies"] == ["community.library_inventory_filtering_v1"]
    assert r.extra["dependency_count"] == 1
    assert r.extra["is_deprecated"] is False
    assert r.extra["is_signed"] is True


def test_parse_blank_description_and_deprecated() -> None:
    r = _provider()._parse(_SAMPLE_RESPONSE, limit=10).results[1]
    assert r.title == "ansible.posix"
    assert r.url == "https://galaxy.ansible.com/ui/repo/published/ansible/posix/"
    # Blank description and no tags -> snippet carries only the populated fields.
    assert r.snippet == "v1.5.4 | requires Ansible >=2.9 | DEPRECATED"
    assert r.extra["requires_ansible"] == ">=2.9"
    assert r.extra["tags"] == []
    assert r.extra["dependencies"] == []
    assert r.extra["is_deprecated"] is True
    assert r.extra["is_signed"] is False
    # No repository timestamp -> no published date rather than a crash.
    assert r.published_date is None
    assert r.rank == 2


def test_parse_collapses_versions_preferring_highest() -> None:
    data = {
        "data": [
            {
                "collection_version": {
                    "namespace": "ns",
                    "name": "c",
                    "version": "1.0.0",
                },
                "is_highest": False,
            },
            {
                "collection_version": {
                    "namespace": "ns",
                    "name": "c",
                    "version": "2.0.0",
                },
                "is_highest": True,
            },
        ]
    }
    result = _provider()._parse(data, limit=10)
    assert len(result.results) == 1
    assert result.results[0].extra["version"] == "2.0.0"


def test_parse_skips_nameless_and_non_dict_items() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=10)
    assert len(result.results) == 2
    assert all("." in r.title for r in result.results)


def test_parse_limit_and_empty() -> None:
    p = _provider()
    assert len(p._parse(_SAMPLE_RESPONSE, limit=1).results) == 1
    assert p._parse(_EMPTY_RESPONSE, limit=10).results == []
    assert p._parse({}, limit=10).results == []  # type: ignore[arg-type]
    assert p._parse([], limit=10).results == []  # type: ignore[arg-type]
    assert p._parse("junk", limit=10).results == []  # type: ignore[arg-type]
    assert p._parse(None, limit=10).results == []  # type: ignore[arg-type]


def test_parse_snippet_capped_at_shared_limit() -> None:
    long_description = "x" * (MAX_SNIPPET_LENGTH + 200)
    result = _provider()._parse(
        {
            "data": [
                {
                    "collection_version": {
                        "namespace": "vendor",
                        "name": "long",
                        "version": "1.0.0",
                        "description": long_description,
                    },
                    "is_highest": True,
                }
            ]
        },
        limit=10,
    )
    assert len(result.results[0].snippet) == MAX_SNIPPET_LENGTH


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_keywords_and_limit(respx_mock) -> None:
    import respx

    respx_mock.get(
        "https://galaxy.ansible.com/api/v3/plugin/ansible/search/collection-versions/"
    ).mock(return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE))

    p = _provider()
    result = await p.search("nginx", SearchParams(num_results=5))

    assert len(result.results) == 2
    request = respx_mock.calls.last.request
    assert request.url.params["keywords"] == "nginx"
    assert request.url.params["offset"] == "0"
    # num_results=5 over-fetches versions before collapsing (5 * 4 = 20).
    assert request.url.params["limit"] == "20"


@pytest.mark.asyncio
async def test_search_blank_query_makes_no_request(respx_mock) -> None:
    route = respx_mock.get(
        "https://galaxy.ansible.com/api/v3/plugin/ansible/search/collection-versions/"
    )

    p = _provider()
    result = await p.search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get(
        "https://galaxy.ansible.com/api/v3/plugin/ansible/search/collection-versions/"
    ).mock(return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE))

    p = _provider()
    result = await p.search("no-such-collection-xyz", SearchParams(num_results=5))
    assert result.results == []
