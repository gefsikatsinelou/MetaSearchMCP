"""Unit tests for the Research Organization Registry (ROR) provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.ror import RorProvider

_SAMPLE_RESPONSE: dict[str, object] = {
    "number_of_results": 3,
    "time_taken": 7,
    "items": [
        {
            "id": "https://ror.org/03vek6s52",
            "names": [
                {
                    "lang": "en",
                    "types": ["ror_display", "label"],
                    "value": "Harvard University",
                },
                {"lang": "es", "types": ["label"], "value": "Universidad de Harvard"},
                {"lang": "en", "types": ["acronym"], "value": "HU"},
                {"lang": "en", "types": ["alias"], "value": "Harvard College"},
            ],
            "links": [
                {"type": "website", "value": "https://www.harvard.edu"},
                {
                    "type": "wikipedia",
                    "value": "https://en.wikipedia.org/wiki/Harvard_University",
                },
            ],
            "locations": [
                {
                    "geonames_id": 4931972,
                    "geonames_details": {
                        "name": "Cambridge",
                        "country_name": "United States",
                        "country_code": "us",
                    },
                },
            ],
            "types": ["education"],
            "status": "active",
            "established": 1636,
            "domains": ["harvard.edu"],
        },
        {
            # No ror_display tag -> falls back to the first available name.
            "id": "https://ror.org/05x88b790",
            "names": [{"types": ["label"], "value": "Harvard Bioscience"}],
            "links": [],
            "locations": [],
            "types": [],
            "status": "inactive",
            "established": None,
        },
        {
            # Missing id -> skipped entirely.
            "names": [{"types": ["ror_display"], "value": "Nameless"}],
        },
        # Non-dict entry -> skipped entirely.
        "junk",
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"number_of_results": 0, "items": []}


def _provider() -> RorProvider:
    return RorProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "ror"
    assert p.tags == ["academic", "organization", "registry"]
    assert p.is_available() is True


def test_parse_basic_fields() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Harvard University"
    assert r.url == "https://www.harvard.edu"
    assert r.provider == "ror"
    assert r.source == "ror.org"
    assert r.rank == 1
    assert "Type: Education" in r.snippet
    assert "Location: Cambridge, United States" in r.snippet
    assert "Established: 1636" in r.snippet
    assert "Acronym: HU" in r.snippet
    assert "Also known as: Harvard College" in r.snippet
    assert r.extra["ror_id"] == "https://ror.org/03vek6s52"
    assert r.extra["city"] == "Cambridge"
    assert r.extra["country"] == "United States"
    assert r.extra["country_code"] == "US"
    assert r.extra["types"] == ["education"]
    assert r.extra["acronyms"] == ["HU"]
    assert r.extra["aliases"] == ["Harvard College"]
    assert r.extra["domains"] == ["harvard.edu"]
    assert r.extra["status"] == "active"
    assert r.extra["established"] == 1636
    assert r.extra["total_results"] == 3


def test_parse_display_name_falls_back_to_first_name() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    second = result.results[1]
    assert second.title == "Harvard Bioscience"
    # No website link -> the ROR id is used as the result URL.
    assert second.url == "https://ror.org/05x88b790"
    assert second.rank == 2
    assert second.extra["status"] == "inactive"
    assert second.extra["established"] == ""
    assert second.snippet == ""


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse({}).results == []
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({"items": "nope"}).results == []
    assert p._parse({"items": [42, None]}).results == []
    assert p._parse("junk").results == []


def test_parse_respects_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1
    assert result.results[0].title == "Harvard University"


def test_parse_ignores_non_list_name_types() -> None:
    data = {
        "items": [
            {
                "id": "https://ror.org/abc",
                "names": [
                    {"types": "ror_display", "value": "Not A List"},
                    {"types": ["acronym"], "value": "NAL"},
                ],
            },
        ],
    }
    result = _provider()._parse(data)

    assert len(result.results) == 1
    # The malformed name entry still provides the fallback display name.
    assert result.results[0].title == "Not A List"
    assert result.results[0].extra["acronyms"] == ["NAL"]


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.ror.org/v2/organizations").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    result = await _provider().search("harvard", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "ror"
    assert len(respx_mock.calls) == 1
    request = respx_mock.calls[0].request
    assert request.url.params["query"] == "harvard"
    assert request.url.params["page"] == "1"


@pytest.mark.asyncio
async def test_search_no_match(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.ror.org/v2/organizations").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    result = await _provider().search("zzzz", SearchParams(num_results=5))
    assert result.results == []
