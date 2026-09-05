"""Unit tests for the pub.dev (Dart/Flutter) package search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.pubdev import PubDevProvider

_SEARCH_RESPONSE: dict[str, object] = {
    "packages": [
        {"package": "http"},
        "http_parser@0.2.0",
        {"package": "dio"},
        {"package": ""},
    ],
}

_META_RESPONSE: dict[str, object] = {
    "name": "http",
    "latest": {
        "version": "1.6.0",
        "published": "2025-11-10T18:27:56.434747Z",
        "pubspec": {
            "name": "http",
            "version": "1.6.0",
            "description": (
                "A composable, multi-platform, Future-based API for HTTP requests."
            ),
            "repository": "https://github.com/dart-lang/http",
            "topics": ["http", "network", "protocols"],
        },
    },
}

_EMPTY_SEARCH: dict[str, object] = {"packages": [], "next": None}


def _provider() -> PubDevProvider:
    return PubDevProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "pubdev"
    assert p.tags == ["web", "code", "developer", "packages"]


def test_parse_search_hits() -> None:
    p = _provider()
    names = p._parse_search_hits(_SEARCH_RESPONSE)
    # Plain string hits, name@version suffixes, and dict entries are all
    # accepted; blank names are skipped and duplicates are dropped.
    assert names == ["http", "http_parser", "dio"]

    assert p._parse_search_hits(_EMPTY_SEARCH) == []
    assert p._parse_search_hits({}) == []
    assert p._parse_search_hits({"packages": [None, 42, {"package": "ok"}]}) == ["ok"]
    assert p._parse_search_hits("junk") == []


def test_result_from_meta() -> None:
    r = _provider()._result_from_meta("http", _META_RESPONSE, rank=1)
    assert r is not None
    assert r.title == "http"
    assert r.url == "https://github.com/dart-lang/http"
    assert "Future-based API for HTTP" in r.snippet
    assert "v1.6.0" in r.snippet
    assert "Topics: http, network, protocols" in r.snippet
    assert r.source == "pub.dev"
    assert r.provider == "pubdev"
    assert r.rank == 1
    assert r.published_date == "2025-11-10"
    assert r.extra["package_name"] == "http"
    assert r.extra["version"] == "1.6.0"
    assert r.extra["repository"] == "https://github.com/dart-lang/http"
    assert r.extra["topics"] == ["http", "network", "protocols"]
    assert r.extra["published_at"] == "2025-11-10T18:27:56.434747Z"


def test_result_from_meta_falls_back_to_canonical_url() -> None:
    meta: dict[str, object] = {
        "latest": {
            "version": "1.0.0",
            "pubspec": {"name": "shelf", "description": "", "repository": ""},
        },
    }
    r = _provider()._result_from_meta("shelf", meta, rank=1)
    assert r is not None
    assert r.url == "https://pub.dev/packages/shelf"
    assert r.published_date is None


def test_result_from_meta_malformed() -> None:
    p = _provider()
    assert p._result_from_meta("x", None, rank=1) is None
    assert p._result_from_meta("x", {}, rank=1) is None
    assert p._result_from_meta("x", {"latest": "junk"}, rank=1) is None


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_and_meta_lookup(respx_mock) -> None:
    import respx

    respx_mock.get("https://pub.dev/api/search").mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE),
    )
    respx_mock.get("https://pub.dev/api/packages/http").mock(
        return_value=respx.MockResponse(200, json=_META_RESPONSE),
    )
    # http_parser returns 404 -> skipped.
    respx_mock.get("https://pub.dev/api/packages/http_parser").mock(
        return_value=respx.MockResponse(404),
    )
    dio_meta: dict[str, object] = {
        "latest": {
            "version": "5.7.0",
            "pubspec": {"description": "Dio is a HTTP client"},
        },
    }
    respx_mock.get("https://pub.dev/api/packages/dio").mock(
        return_value=respx.MockResponse(200, json=dio_meta),
    )

    p = _provider()
    result = await p.search("http", SearchParams(num_results=5))

    assert len(result.results) == 2
    search_call = next(
        c for c in respx_mock.calls if "/api/search" in str(c.request.url)
    )
    assert search_call.request.url.params["q"] == "http"
    # Missing/404 metadata is skipped, so only http and dio survive.
    assert [r.title for r in result.results] == ["http", "dio"]
    assert result.results[0].rank == 1
    assert result.results[1].rank == 2


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://pub.dev/api/search").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_SEARCH),
    )

    p = _provider()
    result = await p.search("no-such-dart-package-xyz", SearchParams(num_results=5))
    assert result.results == []
