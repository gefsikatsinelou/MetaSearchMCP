"""Unit tests for the Hackage (Haskell) package search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.hackage import HackageProvider

_SEARCH_RESPONSE: list[dict[str, str]] = [
    {"name": "http-client"},
    {"name": "http-client-tls"},
    {"name": ""},
    "junk",  # type: ignore[list-item]
]

_VERSION_RESPONSE: dict[str, str] = {
    "0.7.1.2": "normal",
    "0.7.9": "normal",
    "0.6.4.1": "normal",
}

_META_RESPONSE: dict[str, str] = {
    "synopsis": "An HTTP client engine",
    "license": "MIT",
    "homepage": "https://github.com/snoyberg/http-client",
    "version": "0.7.9",
    "uploader": "snoyberg",
    "uploaded_at": "2025-06-01T12:00:00Z",
}

_EMPTY_SEARCH: list[dict[str, str]] = []


def _provider() -> HackageProvider:
    return HackageProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "hackage"
    assert p.tags == ["web", "code", "developer", "packages"]


def test_parse_search_hits() -> None:
    p = _provider()
    assert p._parse_search_hits(_SEARCH_RESPONSE) == ["http-client", "http-client-tls"]
    assert p._parse_search_hits(_EMPTY_SEARCH) == []
    assert p._parse_search_hits({}) == []
    assert p._parse_search_hits("junk") == []
    assert p._parse_search_hits([{"name": "a"}, {"name": "a"}, {"name": "b"}]) == [
        "a",
        "b",
    ]


def test_latest_version() -> None:
    p = _provider()
    # "0.7.9" beats "0.7.1.2" numerically even though it sorts later as text.
    assert p._latest_version(_VERSION_RESPONSE) == "0.7.9"
    assert p._latest_version({}) == ""
    assert p._latest_version("junk") == ""
    assert p._latest_version(None) == ""


def test_result_from_meta() -> None:
    r = _provider()._result_from_meta("http-client", "0.7.9", _META_RESPONSE, rank=1)
    assert r is not None
    assert r.title == "http-client"
    assert r.url == "https://github.com/snoyberg/http-client"
    assert "An HTTP client engine" in r.snippet
    assert "v0.7.9" in r.snippet
    assert "License: MIT" in r.snippet
    assert r.source == "hackage.haskell.org"
    assert r.provider == "hackage"
    assert r.rank == 1
    assert r.published_date == "2025-06-01"
    assert r.extra["package_name"] == "http-client"
    assert r.extra["version"] == "0.7.9"
    assert r.extra["license"] == "MIT"
    assert r.extra["uploader"] == "snoyberg"


def test_result_from_meta_falls_back_to_canonical_url() -> None:
    meta: dict[str, str] = {"synopsis": "", "license": "", "homepage": ""}
    r = _provider()._result_from_meta("aeson", "2.2.0.0", meta, rank=1)
    assert r is not None
    assert r.url == "https://hackage.haskell.org/package/aeson"
    assert r.published_date is None


def test_result_from_meta_malformed() -> None:
    p = _provider()
    assert p._result_from_meta("x", "1.0", None, rank=1) is None
    assert p._result_from_meta("x", "1.0", "junk", rank=1) is None


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_and_meta_lookup(respx_mock) -> None:
    import respx

    respx_mock.get("https://hackage.haskell.org/packages/search.json").mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE)
    )
    # http-client has metadata; http-client-tls returns 404 for its meta
    # lookup (unknown version) so it is skipped.
    respx_mock.get("https://hackage.haskell.org/package/http-client.json").mock(
        return_value=respx.MockResponse(200, json=_VERSION_RESPONSE)
    )
    respx_mock.get("https://hackage.haskell.org/package/http-client-0.7.9.json").mock(
        return_value=respx.MockResponse(200, json=_META_RESPONSE)
    )
    respx_mock.get("https://hackage.haskell.org/package/http-client-tls.json").mock(
        return_value=respx.MockResponse(200, json={})
    )

    p = _provider()
    result = await p.search("http client", SearchParams(num_results=5))

    assert len(result.results) == 1
    search_call = next(
        c for c in respx_mock.calls if "/packages/search.json" in str(c.request.url)
    )
    assert search_call.request.url.params["terms"] == "http client"
    assert [r.title for r in result.results] == ["http-client"]
    assert result.results[0].rank == 1


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://hackage.haskell.org/packages/search.json").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_SEARCH)
    )

    p = _provider()
    result = await p.search("no-such-haskell-package-xyz", SearchParams(num_results=5))
    assert result.results == []
