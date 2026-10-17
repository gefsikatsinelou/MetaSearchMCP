"""Unit tests for the endoflife.date software lifecycle provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.endoflife import EndOfLifeProvider

_ALL_URL = "https://endoflife.date/api/all.json"

_ALL_RESPONSE: list[object] = [
    "python",
    "nodejs",
    "ubuntu",
    "alpine-linux",
    "react",
    "ios",
    "django",
    "amazon-linux",
    None,
    42,
]

# Newest cycle first, as returned by the API.
_NODEJS_CYCLES: list[object] = [
    {
        "cycle": "26",
        "releaseDate": "2026-05-05",
        "lts": "2026-10-28",
        "eol": "2029-04-30",
        "latest": "26.12.0",
        "latestReleaseDate": "2026-10-14",
        "support": "2027-10-27",
        "extendedSupport": False,
    },
    {
        "cycle": "25",
        "releaseDate": "2025-10-15",
        "eol": "2026-06-01",
        "latest": "25.9.0",
        "latestReleaseDate": "2026-04-01",
        "lts": False,
        "support": "2026-04-01",
    },
]

# A cycle using boolean flags instead of dates (still-supported product).
_REACT_CYCLES: list[object] = [
    {
        "cycle": "19",
        "releaseDate": "2024-12-05",
        "eol": False,
        "latest": "19.3.1",
        "latestReleaseDate": "2026-10-14",
        "lts": False,
        "support": True,
    },
]

_UBUNTU_CYCLES: list[object] = [
    {
        "cycle": "26.04",
        "codename": "Resolute Raccoon",
        "lts": True,
        "releaseDate": "2026-04-23",
        "eol": "2031-05-29",
        "latest": "26.04.1",
        "latestReleaseDate": "2026-08-27",
        "support": "2031-05-29",
        "extendedSupport": "2036-04-23",
    },
]


def _provider() -> EndOfLifeProvider:
    return EndOfLifeProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "endoflife"
    assert p.tags == ["web", "developer", "reference", "lifecycle"]
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "endoflife" in registry
    assert registry["endoflife"].tags == ["web", "developer", "reference", "lifecycle"]


def test_date_value_normalisation() -> None:
    assert EndOfLifeProvider._date_value("2026-10-14") == "2026-10-14"
    # Longer ISO datetime strings are truncated to the date prefix.
    assert EndOfLifeProvider._date_value("2026-10-14T00:00:00") == "2026-10-14"
    assert EndOfLifeProvider._date_value("not-a-date") is None
    assert EndOfLifeProvider._date_value(True) is None
    assert EndOfLifeProvider._date_value(None) is None


def test_flag_or_date_normalisation() -> None:
    assert EndOfLifeProvider._flag_or_date("2027-10-27") == "2027-10-27"
    assert EndOfLifeProvider._flag_or_date(True) is True
    assert EndOfLifeProvider._flag_or_date(False) is False
    assert EndOfLifeProvider._flag_or_date(None) is None
    assert EndOfLifeProvider._flag_or_date("") is None


def test_lifecycle_labels() -> None:
    p = _provider()
    assert p._eol_label("2029-04-30") == "EOL 2029-04-30"
    assert p._eol_label(True) == "end-of-life reached"
    assert p._eol_label(False) == ""
    assert p._support_label("2027-10-27") == "support ends 2027-10-27"
    assert p._support_label(True) == "in active support"
    assert p._support_label(False) == ""
    assert p._lts_label("2026-10-28") == "LTS since 2026-10-28"
    assert p._lts_label(True) == "LTS"
    assert p._lts_label(False) == ""


def test_match_products_ranking() -> None:
    p = _provider()
    # Exact slug match wins over substring matches.
    assert p._match_products(_ALL_RESPONSE, "python", 5) == ["python"]
    # "node" matches the "nodejs" slug via a token substring.
    assert "nodejs" in p._match_products(_ALL_RESPONSE, "node", 5)
    # A version token falls back to the leading token match.
    assert p._match_products(_ALL_RESPONSE, "ubuntu 22.04", 5) == ["ubuntu"]
    # No token matches any slug -> empty.
    assert p._match_products(_ALL_RESPONSE, "zzzz", 5) == []
    # Non-list payloads and empty queries are tolerated.
    assert p._match_products(None, "python", 5) == []
    assert p._match_products(_ALL_RESPONSE, "", 5) == []


def test_match_products_respects_limit_and_dedupes() -> None:
    p = _provider()
    matched = p._match_products(_ALL_RESPONSE, "linux", 1)
    assert len(matched) == 1
    # "alpine-linux" and "amazon-linux" both contain "linux"; shorter first.
    assert matched == ["alpine-linux"]
    assert p._match_products(_ALL_RESPONSE, "linux", 5) == [
        "alpine-linux",
        "amazon-linux",
    ]


def test_product_result_basic_fields() -> None:
    result = _provider()._product_result("nodejs", _NODEJS_CYCLES)

    assert result is not None
    assert result.title == "nodejs"
    assert result.url == "https://endoflife.date/nodejs"
    assert result.provider == "endoflife"
    assert result.source == "endoflife.date"
    assert result.published_date == "2026-10-14"
    assert "Latest 26.12.0 (2026-10-14)" in result.snippet
    assert "current cycle 26" in result.snippet
    assert "LTS since 2026-10-28" in result.snippet
    assert "support ends 2027-10-27" in result.snippet
    assert "EOL 2029-04-30" in result.snippet
    assert "2 cycles tracked" in result.snippet
    assert result.extra["product"] == "nodejs"
    assert result.extra["latest_cycle"] == "26"
    assert result.extra["eol"] == "2029-04-30"
    assert len(result.extra["cycles"]) == 2
    assert result.extra["cycles"][1]["cycle"] == "25"
    assert result.extra["cycles"][1]["eol"] == "2026-06-01"


def test_product_result_boolean_flags_and_codename() -> None:
    p = _provider()

    react = p._product_result("react", _REACT_CYCLES)
    assert react is not None
    # Boolean eol False -> no EOL label; support True -> "in active support".
    assert "EOL" not in react.snippet
    assert "in active support" in react.snippet
    assert react.extra["eol"] is False
    assert react.extra["support"] is True

    ubuntu = p._product_result("ubuntu", _UBUNTU_CYCLES)
    assert ubuntu is not None
    assert ubuntu.title == "ubuntu"
    assert "“Resolute Raccoon”" in ubuntu.snippet
    assert "LTS" in ubuntu.snippet
    assert ubuntu.extra["lts"] is True


def test_product_result_skips_unusable_payloads() -> None:
    p = _provider()
    assert p._product_result("python", {}) is None
    assert p._product_result("python", []) is None
    assert p._product_result("python", "junk") is None
    # Entries without any cycle label are dropped; all-dropped -> None.
    assert p._product_result("python", [{"latest": "3.13.0"}]) is None
    # A labelled entry survives even when other entries are junk.
    mixed = p._product_result("python", ["junk", {"releaseLabel": "3.13"}])
    assert mixed is not None
    assert mixed.extra["latest_cycle"] == "3.13"


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get(_ALL_URL).mock(
        return_value=respx.MockResponse(200, json=_ALL_RESPONSE),
    )
    respx_mock.get("https://endoflife.date/api/nodejs.json").mock(
        return_value=respx.MockResponse(200, json=_NODEJS_CYCLES),
    )

    result = await _provider().search("nodejs", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].title == "nodejs"
    assert result.results[0].rank == 1
    assert len(respx_mock.calls) == 2


@pytest.mark.asyncio
async def test_search_no_match_makes_one_request(respx_mock) -> None:
    import respx

    respx_mock.get(_ALL_URL).mock(
        return_value=respx.MockResponse(200, json=_ALL_RESPONSE),
    )

    result = await _provider().search("zzzz", SearchParams(num_results=5))

    assert result.results == []
    assert len(respx_mock.calls) == 1


@pytest.mark.asyncio
async def test_search_tolerates_failing_product_fetch(respx_mock) -> None:
    import respx

    respx_mock.get(_ALL_URL).mock(
        return_value=respx.MockResponse(200, json=_ALL_RESPONSE),
    )
    # Matching "linux" resolves two products; one fails, one succeeds.
    respx_mock.get("https://endoflife.date/api/alpine-linux.json").mock(
        return_value=respx.MockResponse(500),
    )
    respx_mock.get("https://endoflife.date/api/amazon-linux.json").mock(
        return_value=respx.MockResponse(200, json=_UBUNTU_CYCLES),
    )

    result = await _provider().search("linux", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["amazon linux"]
    assert result.results[0].rank == 1
