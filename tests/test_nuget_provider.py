"""Unit tests for the NuGet (.NET) package search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.nuget import NuGetProvider

_SAMPLE_RESPONSE: dict[str, object] = {
    "totalHits": 1054,
    "data": [
        {
            "id": "Newtonsoft.Json",
            "version": "13.0.4",
            "title": "Json.NET",
            "description": (
                "Json.NET is a popular high-performance JSON framework for .NET"
            ),
            "projectUrl": "https://www.newtonsoft.com/json",
            "tags": ["json"],
            "authors": ["James Newton-King"],
            "totalDownloads": 9088085152,
            "verified": True,
        },
        {
            "id": "garbled",
            "version": "",
            "title": " \n ",
            "description": "",
            "authors": [],
            "totalDownloads": 0,
            "verified": False,
        },
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"totalHits": 0, "data": []}


def _provider() -> NuGetProvider:
    return NuGetProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "nuget"
    assert p.tags == ["web", "code", "developer", "packages"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Json.NET"
    assert r.url == "https://www.newtonsoft.com/json"
    assert "high-performance JSON framework" in r.snippet
    assert "v13.0.4" in r.snippet
    assert "Downloads: 9,088,085,152" in r.snippet
    assert r.source == "nuget.org"
    assert r.provider == "nuget"
    assert r.rank == 1
    assert r.extra["package_id"] == "Newtonsoft.Json"
    assert r.extra["version"] == "13.0.4"
    assert r.extra["authors"] == ["James Newton-King"]
    assert r.extra["tags"] == ["json"]
    assert r.extra["total_downloads"] == 9088085152
    assert r.extra["verified"] is True
    assert r.extra["total_hits"] == 1054

    # Second entry has a valid id but blank metadata: title falls back to
    # the package id and the URL to the canonical nuget.org page.
    r2 = result.results[1]
    assert r2.title == "garbled"
    assert r2.url == "https://www.nuget.org/packages/garbled/"
    assert r2.extra["verified"] is False
    assert r2.rank == 2


def test_parse_skips_entry_without_id_and_falls_back_to_title() -> None:
    response: dict[str, object] = {
        "data": [
            {"id": "  ", "version": "1.0.0", "title": "ghost", "description": "x"},
            {"id": "Real.Pkg", "version": "2.0.0", "title": "", "description": "y"},
        ],
    }
    result = _provider()._parse(response)
    assert len(result.results) == 1
    # Title falls back to the package id when the title field is blank.
    assert result.results[0].title == "Real.Pkg"
    assert result.results[0].url == "https://www.nuget.org/packages/Real.Pkg/"


def test_parse_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []
    assert p._parse({"data": ["junk", None, 42]}).results == []
    assert p._parse({"data": None}).results == []
    assert p._parse("junk").results == []  # type: ignore[arg-type]


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_query_and_take(respx_mock) -> None:
    import respx

    respx_mock.get("https://azuresearch-usnc.nuget.org/query").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("newtonsoft", SearchParams(num_results=5))

    assert len(result.results) == 2
    request = respx_mock.calls.last.request
    assert request.url.params["q"] == "newtonsoft"
    assert request.url.params["take"] == "5"
    assert request.url.params["prerelease"] == "false"


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://azuresearch-usnc.nuget.org/query").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("no-such-package-xyz", SearchParams(num_results=5))
    assert result.results == []
