"""Unit tests for the Open VSX extension registry search provider."""

from __future__ import annotations

import httpx
import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.open_vsx import OpenVsxProvider

_SEARCH_RESPONSE: dict[str, object] = {
    "extensions": [
        {
            "namespace": "ms-python",
            "name": "python",
            "displayName": "Python",
            "description": (
                "Python language support with IntelliSense (Pylance), "
                "debugging, linting, and more."
            ),
            "version": "2026.4.0",
            "downloadCount": 57382078,
            "averageRating": 3.875,
            "reviewCount": 16,
            "verified": True,
            "timestamp": "2026-03-13T04:21:53.228120Z",
            "files": {"icon": "https://open-vsx.org/icon/python.png"},
        },
        {
            "namespace": "community",
            "name": "python-fork",
            "displayName": "Python Fork",
            "description": "A small unofficial fork.",
            "version": "1.0.0",
            "downloadCount": 28435,
            "averageRating": None,
            "reviewCount": 0,
            "verified": False,
            "timestamp": None,
            "files": {},
        },
        "junk",  # type: ignore[list-item]
    ],
    "offset": 0,
    "totalSize": 2,
}

_EMPTY_RESPONSE: dict[str, object] = {"extensions": []}


def _provider() -> OpenVsxProvider:
    return OpenVsxProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "open_vsx"
    assert p.tags == ["web", "code", "developer", "plugins"]
    assert "no API key required" in p.description


def test_parse_basic_hit_fields() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)

    assert len(result.results) == 2
    first = result.results[0]
    assert first.title == "Python"
    assert first.url == "https://open-vsx.org/extension/ms-python/python"
    assert first.source == "open-vsx.org"
    assert first.provider == "open_vsx"
    assert first.rank == 1
    assert "IntelliSense" in first.snippet
    assert "v2026.4.0" in first.snippet
    assert "Downloads: 57,382,078" in first.snippet
    assert "Rating: 3.88" in first.snippet
    assert "Reviews: 16" in first.snippet
    assert "Verified publisher" in first.snippet
    assert first.published_date == "2026-03-13"
    assert first.extra["extension_id"] == "ms-python.python"
    assert first.extra["namespace"] == "ms-python"
    assert first.extra["downloads"] == 57382078
    assert first.extra["rating"] == 3.88
    assert first.extra["review_count"] == 16
    assert first.extra["verified"] is True
    assert first.extra["icon"] == "https://open-vsx.org/icon/python.png"


def test_parse_reranks_by_downloads() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    # Higher-download extension surfaces first regardless of API order.
    assert result.results[0].title == "Python"
    assert result.results[1].title == "Python Fork"


def test_parse_unverified_and_missing_fields() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE)
    second = result.results[1]
    assert "Unverified publisher" in second.snippet
    assert "Verified publisher" not in second.snippet
    assert second.published_date is None
    assert second.extra["rating"] is None
    assert second.extra["review_count"] == 0
    assert second.extra["icon"] == ""


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []
    assert p._parse(None).results == []
    assert p._parse("junk").results == []
    assert p._parse({"extensions": "junk"}).results == []
    assert p._parse({"extensions": [{}]}).results == []


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse(_SEARCH_RESPONSE, limit=1).results) == 1


def test_parse_missing_namespace_and_name() -> None:
    p = _provider()
    result = p._parse({"extensions": [{"displayName": "Standalone"}]})
    assert len(result.results) == 1
    assert result.results[0].url == "https://open-vsx.org"
    assert result.results[0].extra["extension_id"] == ""


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_gets_api(respx_mock) -> None:
    import respx

    respx_mock.get("https://open-vsx.org/api/-/search").mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE)
    )

    p = _provider()
    result = await p.search("python", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].title == "Python"
    call = respx_mock.calls[0]
    assert "query=python" in str(call.request.url)
    assert "size=5" in str(call.request.url)


@pytest.mark.asyncio
async def test_search_http_error_raises(respx_mock) -> None:
    import respx

    respx_mock.get("https://open-vsx.org/api/-/search").mock(
        return_value=respx.MockResponse(500)
    )

    p = _provider()
    with pytest.raises(httpx.HTTPStatusError):
        await p.search("python", SearchParams(num_results=5))
