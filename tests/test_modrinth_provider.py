"""Unit tests for the Modrinth Minecraft content search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH
from metasearchmcp.providers.modrinth import ModrinthProvider

_SAMPLE_RESPONSE: dict[str, object] = {
    "hits": [
        {
            "project_id": "AANobbMI",
            "project_type": "mod",
            "slug": "sodium",
            "author": "jellysquid3",
            "organization": "CaffeineMC",
            "title": "Sodium",
            "description": (
                "A high-performance rendering engine replacement for Minecraft, "
                "which greatly improves frame rates and reduces micro-stutter."
            ),
            "categories": ["fabric", "neoforge", "optimization", "quilt"],
            "display_categories": ["fabric", "neoforge", "optimization", "quilt"],
            "versions": ["1.20.1", "1.21.1", "1.21.11"],
            "downloads": 228694255,
            "follows": 40807,
            "icon_url": "https://cdn.modrinth.com/data/AANobbMI/icon.webp",
            "date_created": "2021-01-03T00:53:34.185936+00:00",
            "date_modified": "2026-09-20T21:27:06.329936+00:00",
            "latest_version": "NM9w06Kr",
            "license": "LicenseRef-Polyform-Shield-1.0.0",
            "client_side": "required",
            "server_side": "unsupported",
        },
        {
            # No slug and no date_created -> fallback search URL, no date.
            "project_id": "PLUGIN1",
            "project_type": "plugin",
            "title": "WorldEdit",
            "description": "In-game map editor.",
            "categories": ["bukkit", "management", "paper", "spigot"],
            "versions": ["1.21", "1.21.1"],
            "downloads": 10722984,
            "follows": 4770,
            "license": "GPL-3.0-only",
            "client_side": "unsupported",
            "server_side": "required",
        },
        {
            # Missing title -> skipped.
            "project_id": "BAD",
            "description": "No title here",
        },
        {
            # Duplicate project id -> collapsed onto the first occurrence.
            "project_id": "AANobbMI",
            "slug": "sodium-again",
            "title": "Sodium Again",
        },
        "junk",
        None,
    ],
    "offset": 0,
    "limit": 10,
    "total_hits": 351,
}

_EMPTY_RESPONSE: dict[str, object] = {
    "hits": [],
    "offset": 0,
    "limit": 10,
    "total_hits": 0,
}


def _provider() -> ModrinthProvider:
    return ModrinthProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "modrinth"
    assert p.tags == ["web", "media", "games", "mods"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Sodium"
    assert r.url == "https://modrinth.com/mod/sodium"
    assert "rendering engine replacement" in r.snippet
    assert "Mod" in r.snippet
    assert "fabric, neoforge, quilt" in r.snippet
    assert "MC 1.21.11" in r.snippet
    assert "228,694,255 downloads" in r.snippet
    assert "40,807 followers" in r.snippet
    assert "LicenseRef-Polyform-Shield-1.0.0" in r.snippet
    assert r.source == "modrinth.com"
    assert r.provider == "modrinth"
    assert r.rank == 1
    assert r.published_date == "2021-01-03"
    assert r.extra["project_id"] == "AANobbMI"
    assert r.extra["slug"] == "sodium"
    assert r.extra["project_type"] == "mod"
    assert r.extra["author"] == "jellysquid3"
    assert r.extra["organization"] == "CaffeineMC"
    assert r.extra["downloads"] == 228694255
    assert r.extra["follows"] == 40807
    assert r.extra["license"] == "LicenseRef-Polyform-Shield-1.0.0"
    assert r.extra["client_side"] == "required"
    assert r.extra["server_side"] == "unsupported"
    assert r.extra["latest_version"] == "NM9w06Kr"
    assert r.extra["icon_url"] == "https://cdn.modrinth.com/data/AANobbMI/icon.webp"
    assert r.extra["date_modified"] == "2026-09-20T21:27:06.329936+00:00"
    assert r.extra["total_results"] == 351


def test_parse_splits_categories_and_loaders() -> None:
    results = _provider()._parse(_SAMPLE_RESPONSE).results
    assert results[0].extra["categories"] == ["optimization"]
    assert results[0].extra["loaders"] == ["fabric", "neoforge", "quilt"]
    # Loader slugs are reported separately for server plugins as well.
    assert results[1].extra["categories"] == ["management"]
    assert results[1].extra["loaders"] == ["bukkit", "paper", "spigot"]


def test_parse_caps_game_versions() -> None:
    from metasearchmcp.providers.modrinth import _MAX_GAME_VERSIONS

    many = [f"1.21.{n}" for n in range(_MAX_GAME_VERSIONS + 10)]
    result = _provider()._parse(
        {"hits": [{"project_id": "X", "title": "Many", "versions": many}]}
    )
    assert len(result.results[0].extra["game_versions"]) == _MAX_GAME_VERSIONS


def test_parse_url_fallback_without_slug() -> None:
    r = _provider()._parse(_SAMPLE_RESPONSE).results[1]
    assert r.url == "https://modrinth.com/search?q=WorldEdit"
    assert r.published_date is None
    assert r.extra["slug"] == ""
    assert r.extra["date_modified"] is None
    assert r.extra["organization"] is None
    assert "Plugin" in r.snippet
    assert "MC 1.21.1" in r.snippet


def test_parse_skips_nameless_and_non_dict_items() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert [r.title for r in result.results] == ["Sodium", "WorldEdit"]


def test_parse_limit_and_empty() -> None:
    p = _provider()
    assert len(p._parse(_SAMPLE_RESPONSE, limit=1).results) == 1
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse("junk").results == []  # type: ignore[arg-type]
    assert p._parse(None).results == []  # type: ignore[arg-type]
    assert p._parse({}).results == []  # type: ignore[arg-type]
    assert p._parse({"hits": "junk"}).results == []  # type: ignore[arg-type]


def test_parse_snippet_truncates_long_description() -> None:
    from metasearchmcp.providers.modrinth import _MAX_SNIPPET_DESCRIPTION

    long_text = "x" * (MAX_SNIPPET_LENGTH + 200)
    result = _provider()._parse(
        {
            "hits": [
                {
                    "project_id": "LONG",
                    "slug": "long",
                    "title": "Long",
                    "description": long_text,
                }
            ]
        }
    )
    snippet = result.results[0].snippet
    assert len(snippet) == _MAX_SNIPPET_DESCRIPTION
    assert snippet.endswith("…")


def test_parse_snippet_capped_at_shared_limit() -> None:
    from metasearchmcp.providers.modrinth import _LOADERS

    # A description at the truncation limit plus a long metadata tail is
    # still capped at the shared snippet length.
    description = "x" * (MAX_SNIPPET_LENGTH - 180)
    result = _provider()._parse(
        {
            "hits": [
                {
                    "project_id": "LONG",
                    "slug": "long",
                    "title": "Long",
                    "description": description,
                    "categories": sorted(_LOADERS),
                    "versions": ["1.21"],
                    "downloads": 1,
                    "follows": 1,
                    "license": "MIT",
                }
            ]
        }
    )
    snippet = result.results[0].snippet
    assert len(snippet) == MAX_SNIPPET_LENGTH
    assert snippet.startswith(description)


def test_parse_tolerates_missing_optional_fields() -> None:
    result = _provider()._parse(
        {"hits": [{"project_id": "MIN", "slug": "min", "title": "Minimal"}]}
    )
    r = result.results[0]
    assert r.snippet == ""
    assert r.extra["downloads"] is None
    assert r.extra["follows"] is None
    assert r.extra["categories"] == []
    assert r.extra["loaders"] == []
    assert r.extra["game_versions"] == []


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_query_and_limit(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.modrinth.com/v2/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("  optimization  ", SearchParams(num_results=5))

    assert len(result.results) == 2
    request = respx_mock.calls.last.request
    # Whitespace in the query is collapsed before the request is sent.
    assert request.url.params["query"] == "optimization"
    assert request.url.params["limit"] == "5"


@pytest.mark.asyncio
async def test_search_blank_query_makes_no_request(respx_mock) -> None:
    import respx

    route = respx_mock.get("https://api.modrinth.com/v2/search").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    assert (await p.search("   ", SearchParams(num_results=5))).results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_no_results_returns_empty(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.modrinth.com/v2/search").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("zzzznotathing", SearchParams(num_results=5))
    assert result.results == []


@pytest.mark.asyncio
async def test_search_bad_request_returns_empty(respx_mock) -> None:
    import respx

    # Modrinth answers a malformed search request with HTTP 400.
    respx_mock.get("https://api.modrinth.com/v2/search").mock(
        return_value=respx.MockResponse(400, json={"error": "invalid request"}),
    )

    p = _provider()
    result = await p.search("sodium", SearchParams(num_results=5))
    assert result.results == []
