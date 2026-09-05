"""Unit tests for the Anaconda (conda package) search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.anaconda import AnacondaProvider

# Two personal forks of "requests" plus the curated conda-forge one.
_SEARCH_RESPONSE: list[dict[str, object]] = [
    {
        "name": "requests",
        "full_name": "asmeurer/requests",
        "owner": "asmeurer",
        "latest_version": "2.0.1",
        "summary": "http://python-requests.org",
        "license": "Apache Software License",
        "ndownloads": 1000,
    },
    {
        "name": "requests",
        "full_name": "conda-forge/requests",
        "owner": "conda-forge",
        "latest_version": "2.32.5",
        "summary": "Python HTTP for Humans.",
        "license": "Apache-2.0",
        "home": "https://requests.readthedocs.io",
        "ndownloads": 5000,
    },
    {
        "name": "requests",
        "full_name": "barnybug/requests",
        "owner": "barnybug",
        "latest_version": "0.12.1",
        "summary": "",
        "ndownloads": 900,
    },
    {
        "name": "polars",
        "full_name": "conda-forge/polars",
        "owner": "conda-forge",
        "latest_version": "1.44.1",
        "summary": "Blazingly fast DataFrame library",
        "ndownloads": 3000,
    },
    "junk",  # type: ignore[list-item]
]

_EMPTY_SEARCH: list[dict[str, str]] = []


def _provider() -> AnacondaProvider:
    return AnacondaProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "anaconda"
    assert p.tags == ["web", "code", "developer", "packages"]


def test_dedupe_prefers_curated_channel() -> None:
    p = _provider()
    deduped = p._dedupe_packages(_SEARCH_RESPONSE)
    by_name = {item["name"]: item for item in deduped}
    # Curated conda-forge copy wins over personal forks for "requests".
    assert by_name["requests"]["full_name"] == "conda-forge/requests"
    assert by_name["polars"]["full_name"] == "conda-forge/polars"


def test_sort_key_orders_curated_first() -> None:
    p = _provider()
    key_conda_forge = p._sort_key({"owner": "conda-forge", "ndownloads": 1})
    key_bioconda = p._sort_key({"owner": "bioconda", "ndownloads": 1})
    key_personal = p._sort_key({"owner": "asmeurer", "ndownloads": 99})
    assert key_conda_forge < key_bioconda < key_personal


def test_parse_keeps_best_hit_per_name() -> None:
    p = _provider()
    result = p._parse(_SEARCH_RESPONSE, limit=10)
    titles = [r.title for r in result.results]
    assert titles == ["conda-forge/requests", "conda-forge/polars"]

    first = result.results[0]
    assert first.title == "conda-forge/requests"
    assert first.url == "https://anaconda.org/conda-forge/requests"
    assert first.source == "anaconda.org"
    assert first.provider == "anaconda"
    assert first.rank == 1
    assert "[conda-forge]" in first.snippet
    assert "Python HTTP for Humans." in first.snippet
    assert "v2.32.5" in first.snippet
    assert first.extra["package_name"] == "requests"
    assert first.extra["channel"] == "conda-forge"
    assert first.extra["version"] == "2.32.5"
    assert first.extra["license"] == "Apache-2.0"
    assert first.extra["downloads"] == 5000

    second = result.results[1]
    assert second.title == "conda-forge/polars"
    assert second.rank == 2


def test_parse_malformed() -> None:
    p = _provider()
    assert p._parse(None, limit=5).results == []
    assert p._parse("junk", limit=5).results == []
    assert p._parse({}, limit=5).results == []
    assert p._parse([{"name": ""}], limit=5).results == []
    assert p._parse(_EMPTY_SEARCH, limit=5).results == []


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse(_SEARCH_RESPONSE, limit=1).results) == 1


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_success(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.anaconda.org/search").mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE)
    )

    p = _provider()
    result = await p.search("requests", SearchParams(num_results=5))

    assert [r.title for r in result.results] == [
        "conda-forge/requests",
        "conda-forge/polars",
    ]
    search_call = next(c for c in respx_mock.calls if "/search" in str(c.request.url))
    assert search_call.request.url.params["name"] == "requests"


@pytest.mark.asyncio
async def test_search_fills_missing_latest_version(respx_mock) -> None:
    import respx

    partial = [
        {
            "name": "zstd",
            "full_name": "conda-forge/zstd",
            "owner": "conda-forge",
            "summary": "Zstandard compression",
            "latest_version": "",
        },
        {
            "name": "zstd",
            "full_name": "asmeurer/zstd",
            "owner": "asmeurer",
            "latest_version": "1.0.0",
            "summary": "fork",
        },
    ]
    respx_mock.get("https://api.anaconda.org/search").mock(
        return_value=respx.MockResponse(200, json=partial)
    )
    respx_mock.get("https://api.anaconda.org/package/conda-forge/zstd").mock(
        return_value=respx.MockResponse(200, json={"latest_version": "1.5.6"})
    )

    p = _provider()
    result = await p.search("zstd", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].title == "conda-forge/zstd"
    assert result.results[0].extra["version"] == "1.5.6"


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.anaconda.org/search").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_SEARCH)
    )

    p = _provider()
    result = await p.search("no-such-conda-package-xyz", SearchParams(num_results=5))
    assert result.results == []
