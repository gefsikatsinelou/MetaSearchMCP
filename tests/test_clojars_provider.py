"""Unit tests for the Clojars (Clojure) search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.providers.clojars import ClojarsProvider

_SAMPLE_RESPONSE = {
    "count": 2,
    "total-hits": 2,
    "results-per-page": 24,
    "offset": 0,
    "results": [
        {
            "created": "1750963042965",
            "description": (
                "A Clojure HTTP library wrapping the Apache HttpComponents client."
            ),
            "group_name": "clj-http",
            "jar_name": "clj-http",
            "version": "3.13.1",
        },
        {
            "created": "1600000000000",
            "description": "Missing coordinates",
            "group_name": "",
            "jar_name": "orphan",
            "version": "1.0",
        },
    ],
}

_EMPTY_RESPONSE = {"count": 0, "total-hits": 0, "results": []}


def test_clojars_parse_basic():
    p = ClojarsProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "clj-http/clj-http"
    assert r.url == "https://clojars.org/clj-http/clj-http"
    assert "v3.13.1" in r.snippet
    assert "Clojure HTTP library" in r.snippet
    assert r.source == "Clojars"
    assert r.provider == "clojars"
    assert r.rank == 1
    assert r.published_date == "2025-06-26"
    assert r.extra["group"] == "clj-http"
    assert r.extra["artifact"] == "clj-http"
    assert r.extra["latest_version"] == "3.13.1"


def test_clojars_parse_skips_entry_without_coordinates():
    p = ClojarsProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    # Second entry has an empty group_name -> skipped.
    assert len(result.results) == 1
    assert all(r.extra["group"] for r in result.results)


def test_clojars_parse_empty():
    p = ClojarsProvider()
    assert p._parse(_EMPTY_RESPONSE).results == []


def test_clojars_parse_missing_results_key():
    p = ClojarsProvider()
    assert p._parse({"count": 0}).results == []


def test_clojars_parse_missing_keys():
    p = ClojarsProvider()
    result = p._parse(
        {
            "results": [
                {"group_name": "org.example", "jar_name": "demo"},
            ],
        },
    )
    r = result.results[0]
    assert r.title == "org.example/demo"
    assert r.snippet == ""
    assert r.published_date is None
    assert r.extra["latest_version"] == ""


def test_clojars_timestamp_to_date():
    assert ClojarsProvider._timestamp_to_date(1750963042965) == "2025-06-26"
    assert ClojarsProvider._timestamp_to_date(None) is None
    assert ClojarsProvider._timestamp_to_date("") is None
    assert ClojarsProvider._timestamp_to_date("not-a-number") is None
    assert ClojarsProvider._timestamp_to_date(0) is None


def test_clojars_artifact_url():
    assert ClojarsProvider._artifact_url("org.example", "demo") == (
        "https://clojars.org/org.example/demo"
    )


def test_clojars_is_available():
    """Keyless provider is always available."""
    assert ClojarsProvider().is_available() is True


@pytest.mark.asyncio
async def test_clojars_search_builds_query(respx_mock):
    """The search method hits the JSON endpoint and parses the response."""
    import respx

    respx_mock.get("https://clojars.org/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    from metasearchmcp.contracts import SearchParams

    p = ClojarsProvider()
    result = await p.search("http", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "clojars"
    request = respx_mock.calls.last.request
    assert request.url.params["q"] == "http"
    assert request.url.params["format"] == "json"


@pytest.mark.asyncio
async def test_clojars_search_blank_query_skips_request(respx_mock):
    """A blank query performs no HTTP request."""

    p = ClojarsProvider()
    result = await p.search("   ", _params())
    assert result.results == []
    assert respx_mock.calls.call_count == 0


def _params():
    from metasearchmcp.contracts import SearchParams

    return SearchParams(num_results=5)
