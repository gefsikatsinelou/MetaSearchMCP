"""Unit tests for the Nager.Date public-holiday search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.nager import _CURRENT_YEAR, NagerDateProvider

_SAMPLE_RESPONSE: list[dict[str, object]] = [
    {
        "date": "2026-12-25",
        "localName": "Weihnachtstag",
        "name": "Christmas Day",
        "countryCode": "DE",
        "fixed": False,
        "global": True,
        "counties": None,
        "launchYear": None,
        "types": ["Public"],
    },
    {
        "date": "2026-01-06",
        "localName": "Heilige Drei Könige",
        "name": "Epiphany",
        "countryCode": "DE",
        "fixed": False,
        "global": False,
        "counties": ["DE-BW", "DE-BY", "DE-ST"],
        "launchYear": None,
        "types": ["Public"],
    },
    {
        # Missing date -> skipped.
        "name": "Incomplete",
        "countryCode": "DE",
    },
]

_EMPTY_RESPONSE: list[dict[str, object]] = []


def _provider() -> NagerDateProvider:
    return NagerDateProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "nager"
    assert p.tags == ["reference", "calendar", "places"]


def test_resolve_iso_code_case_insensitive() -> None:
    p = _provider()
    assert p._resolve("US") == "US"
    assert p._resolve("de") == "DE"
    assert p._resolve(" jp ") == "JP"


def test_resolve_common_names() -> None:
    p = _provider()
    assert p._resolve("japan") == "JP"
    assert p._resolve("United Kingdom") == "GB"
    assert p._resolve("germany") == "DE"
    assert p._resolve("usa") == "US"


def test_resolve_unknown_returns_empty() -> None:
    p = _provider()
    assert p._resolve("") == ""
    assert p._resolve("atlantis") == ""
    assert p._resolve("ZZ") == "ZZ"  # any 2-letter alpha token maps verbatim


def test_year_of() -> None:
    p = _provider()
    assert p._year_of("germany 1990") == "1990"
    assert p._year_of("US 2024") == "2024"
    assert p._year_of("de") is None
    assert p._year_of("france") is None
    assert p._year_of("in 1800") is None  # too early for the calendar era
    assert p._year_of("year 2999") is None  # far future


def test_resolve_ignores_standalone_year_tokens() -> None:
    p = _provider()
    assert p._resolve("germany 1990") == "DE"
    assert p._resolve("US 2024") == "US"
    assert p._resolve("1990 germany") == "DE"
    assert p._resolve("2024") == ""
    assert p._resolve("US2024") == ""  # not a standalone token -> no match
    assert p._resolve("us holidays 2024") == ""  # remainder is not an alias


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, "DE")

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Christmas Day (2026-12-25)"
    assert r.url == "https://date.nager.at/PublicHoliday/DE/2026-12-25"
    assert "DE" in r.snippet
    assert "nationwide" in r.snippet
    assert "Type: Public" in r.snippet
    assert "Local: Weihnachtstag" in r.snippet
    assert r.provider == "nager"
    assert r.source == "date.nager.at"
    assert r.rank == 1
    assert r.published_date == "2026-12-25"
    assert r.extra["country_code"] == "DE"
    assert r.extra["global"] is True
    assert r.extra["types"] == ["Public"]


def test_parse_regional_holiday_flags() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, "DE")
    r = result.results[1]
    assert r.title == "Epiphany (2026-01-06)"
    assert "3 regions only" in r.snippet
    assert "nationwide" not in r.snippet
    assert r.extra["counties"] == ["DE-BW", "DE-BY", "DE-ST"]
    assert r.extra["global"] is False


def test_parse_skips_incomplete() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, "DE")
    assert all(r.title and r.url for r in result.results)


def test_parse_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, "DE", limit=1)
    assert len(result.results) == 1
    assert result.results[0].title == "Christmas Day (2026-12-25)"


def test_parse_empty_and_malformed() -> None:
    assert _provider()._parse(_EMPTY_RESPONSE, "DE").results == []
    assert _provider()._parse(None, "DE").results == []
    assert _provider()._parse({"results": []}, "DE").results == []
    assert _provider()._parse("junk", "DE").results == []


def test_parse_uses_fallback_country_code() -> None:
    """Worldwide fallback responses carry their own countryCode."""
    worldwide = [
        {"date": "2026-09-03", "name": "National Day", "countryCode": "VN"},
    ]
    result = _provider()._parse(worldwide, "")
    assert result.results[0].extra["country_code"] == "VN"


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


def test_current_year_is_sane() -> None:
    """Module-level current year must look like a real year."""
    assert 2020 <= _CURRENT_YEAR <= 2100


@pytest.mark.asyncio
async def test_search_hits_country_endpoint_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get(
        f"https://date.nager.at/api/v3/PublicHolidays/{_CURRENT_YEAR}/DE",
    ).mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("DE", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "nager"
    assert result.results[0].published_date == "2026-12-25"


@pytest.mark.asyncio
async def test_search_defaults_to_current_year(respx_mock) -> None:
    import respx

    respx_mock.get(
        f"https://date.nager.at/api/v3/PublicHolidays/{_CURRENT_YEAR}/JP",
    ).mock(return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE))

    p = _provider()
    result = await p.search("japan", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_search_uses_resolved_year_from_query(respx_mock) -> None:
    """A four-digit year in the query selects that holiday year."""
    import respx

    respx_mock.get(
        "https://date.nager.at/api/v3/PublicHolidays/1990/DE",
    ).mock(return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE))

    p = _provider()
    result = await p.search("germany 1990", SearchParams(num_results=5))

    assert len(result.results) == 2
    request = respx_mock.calls.last.request
    assert request.url.path.endswith("/PublicHolidays/1990/DE")


@pytest.mark.asyncio
async def test_search_unresolved_query_uses_worldwide_endpoint(respx_mock) -> None:
    import respx

    worldwide = [
        {"date": "2026-12-25", "name": "Christmas Day", "countryCode": "US"},
    ]
    respx_mock.get(
        "https://date.nager.at/api/v3/NextPublicHolidaysWorldwide",
    ).mock(return_value=respx.MockResponse(200, json=worldwide))

    p = _provider()
    result = await p.search("flying spaghetti monster", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].extra["country_code"] == "US"
    assert result.results[0].provider == "nager"
