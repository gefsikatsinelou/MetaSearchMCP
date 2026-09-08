"""Unit tests for the VS Code Marketplace search provider."""

from __future__ import annotations

import json

import httpx
import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.vscode_marketplace import VSCodeMarketplaceProvider

_SEARCH_RESPONSE: dict[str, object] = {
    "results": [
        {
            "extensions": [
                {
                    "extensionId": "f1f59ae4-9318-4f3c-a9b5-81b2eaa5f8a5",
                    "extensionName": "python",
                    "displayName": "Python",
                    "publisher": {
                        "publisherName": "ms-python",
                        "displayName": "Microsoft",
                        "flags": "verified",
                    },
                    "shortDescription": (
                        "IntelliSense, linting, debugging, and testing for Python."
                    ),
                    "publishedDate": "2017-01-01T00:00:00Z",
                    "lastUpdated": "2026-08-26T11:08:55.123Z",
                    "versions": [
                        {
                            "version": "2026.10.0",
                            "lastUpdated": "2026-08-26T11:08:55.123Z",
                        }
                    ],
                    "statistics": [
                        {"statisticName": "install", "value": 123456789.0},
                        {"statisticName": "averagerating", "value": 4.87},
                        {"statisticName": "ratingcount", "value": 1200.0},
                    ],
                },
                {
                    # Low-install lookalike: should be re-ranked after the
                    # canonical one.
                    "extensionId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "extensionName": "python-nightly",
                    "displayName": "Python Nightly",
                    "publisher": {
                        "publisherName": "nightly-bot",
                        "displayName": "Nightly Bot",
                    },
                    "shortDescription": "Nightly build of the Python extension.",
                    "publishedDate": "2024-05-05T00:00:00Z",
                    "versions": [{"version": "2026.1.0"}],
                    "statistics": [
                        {"statisticName": "install", "value": 42.0},
                        {"statisticName": "averagerating", "value": 5.0},
                        {"statisticName": "ratingcount", "value": 3.0},
                    ],
                },
                # No publisher name -> no canonical URL can be built; dropped.
                {
                    "extensionName": "orphan",
                    "displayName": "Orphan",
                    "publisher": {"displayName": "No publisher name"},
                    "versions": [{"version": "1.0.0"}],
                },
                # Missing extension name -> dropped.
                {
                    "displayName": "Nameless",
                    "publisher": {"publisherName": "some-publisher"},
                    "versions": [{"version": "1.0.0"}],
                },
                "junk",  # type: ignore[list-item]
            ]
        }
    ]
}

_EMPTY_RESPONSE: dict[str, object] = {"results": [{"extensions": []}]}


def _provider() -> VSCodeMarketplaceProvider:
    return VSCodeMarketplaceProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "vscode_marketplace"
    assert p.tags == ["web", "code", "developer", "plugins"]
    assert "no API key required" in p.description


def test_parse_basic_hit_fields() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)

    assert len(result.results) == 2
    first = result.results[0]
    assert first.title == "Python"
    assert (
        first.url
        == "https://marketplace.visualstudio.com/items?itemName=ms-python.python"
    )
    assert first.source == "marketplace.visualstudio.com"
    assert first.provider == "vscode_marketplace"
    assert first.rank == 1
    assert first.published_date == "2017-01-01"
    assert "IntelliSense" in first.snippet
    assert "v2026.10.0" in first.snippet
    assert "Installs: 123,456,789" in first.snippet
    assert "Rating: 4.87/5 (1200)" in first.snippet
    assert "Publisher: Microsoft" in first.snippet
    assert first.extra["extension_id"] == "f1f59ae4-9318-4f3c-a9b5-81b2eaa5f8a5"
    assert first.extra["extension_name"] == "python"
    assert first.extra["publisher"] == "ms-python"
    assert first.extra["installs"] == 123456789
    assert first.extra["rating"] == 4.87
    assert first.extra["rating_count"] == 1200
    assert first.extra["last_updated"] == "2026-08-26"


def test_parse_reranks_by_installs() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    # Canonical (high-install) extension surfaces before the niche lookalike.
    assert result.results[0].extra["extension_name"] == "python"
    assert result.results[1].extra["extension_name"] == "python-nightly"


def test_parse_skips_unusable_records() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    # Records lacking publisher name or extension name are dropped.
    dropped = {"orphan", "Nameless"}
    assert all(r.extra["extension_name"] not in dropped for r in result.results)
    assert all(r.title not in dropped for r in result.results)


def test_parse_missing_fields() -> None:
    p = _provider()
    hit = {
        "extensionName": "minimal",
        "displayName": "Minimal",
        "publisher": {"publisherName": "min-pub"},
        "publishedDate": "junk",
        "statistics": "junk",
    }
    result = p._parse({"results": [{"extensions": [hit]}]})
    assert len(result.results) == 1
    r = result.results[0]
    assert r.published_date is None
    assert r.extra["installs"] == 0
    assert r.extra["rating"] is None
    assert r.extra["version"] == ""
    assert r.extra["publisher"] == "min-pub"
    assert r.snippet == "Publisher: min-pub"


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []
    assert p._parse(None).results == []
    assert p._parse("junk").results == []
    assert p._parse({"results": "junk"}).results == []
    assert p._parse({"results": [{"extensions": [{}]}]}).results == []


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse(_SEARCH_RESPONSE, limit=1).results) == 1


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_posts_extensionquery(respx_mock) -> None:
    import respx

    respx_mock.post(
        "https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery"
    ).mock(return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE))

    p = _provider()
    result = await p.search("python", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].title == "Python"
    call = respx_mock.calls[0]
    body = call.request.content
    assert b"python" in body
    request_json = json.loads(call.request.content)
    filters = request_json["filters"]
    assert filters[0]["criteria"] == [{"filterType": 10, "value": "python"}]
    assert filters[0]["pageSize"] == 5
    assert "api-version=3.0-preview.1" in call.request.headers["accept"]


@pytest.mark.asyncio
async def test_search_http_error_raises(respx_mock) -> None:
    import respx

    respx_mock.post(
        "https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery"
    ).mock(return_value=respx.MockResponse(500))

    p = _provider()
    with pytest.raises(httpx.HTTPStatusError):
        await p.search("python", SearchParams(num_results=5))
