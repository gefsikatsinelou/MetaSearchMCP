"""Unit tests for the NASA Exoplanet Archive provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.exoplanet import ExoplanetProvider

_TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"

# A single-planet system: exercises the per-planet measurements.
_TRAPPIST_ROW = {
    "pl_name": "TRAPPIST-1 e",
    "hostname": "TRAPPIST-1",
    "disc_year": 2017,
    "discoverymethod": "Transit",
    "disc_facility": "Spitzer",
    "pl_orbper": 6.099043,
    "pl_orbsmax": 0.02928285,
    "pl_rade": 0.92000000,
    "pl_bmasse": 0.77200000,
    "pl_bmassprov": "Mass",
    "pl_eqt": 251.0,
    "sy_dist": 12.4292,
    "sy_snum": 1,
    "sy_pnum": 7,
}

# A circumbinary planet: ``sy_snum`` counts the stars in the system.
_KEPLER_16_ROW = {
    "pl_name": "Kepler-16 b",
    "hostname": "Kepler-16",
    "disc_year": 2011,
    "discoverymethod": "Transit",
    "disc_facility": "Kepler",
    "pl_orbper": 228.776,
    "pl_orbsmax": 0.7048,
    "pl_rade": 8.4493,
    "pl_bmasse": 105.833,
    "pl_bmassprov": "Mass",
    "pl_eqt": 205.90,
    "sy_dist": 75.0852,
    "sy_snum": 2,
    "sy_pnum": 1,
}

_PAYLOAD: list[object] = [
    _TRAPPIST_ROW,
    _KEPLER_16_ROW,
    # A row without a planet name carries no usable hit.
    {"pl_name": "", "hostname": "Nameless"},
    "not-a-mapping",
]


def _provider() -> ExoplanetProvider:
    """Return a fresh provider instance for each test."""
    return ExoplanetProvider()


def _mock_search(respx_mock, payload: object = _PAYLOAD):
    """Route TAP calls to *payload*."""
    return respx_mock.get(_TAP_URL).mock(
        return_value=respx.MockResponse(200, json=payload),
    )


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "exoplanet"
    assert p.tags == ["space", "science", "reference"]
    assert "keyless" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "exoplanet" in registry
    assert registry["exoplanet"].tags == ["space", "science", "reference"]


def test_adql_statement_structure() -> None:
    adql = ExoplanetProvider._adql("trappist-1", 15)

    assert adql.startswith("select top 15 pl_name, hostname, disc_year")
    assert " from pscomppars " in adql
    assert "pl_name like '%trappist-1%'" in adql
    assert "hostname like '%trappist-1%'" in adql
    assert adql.endswith("order by pl_name")


def test_adql_escapes_single_quotes() -> None:
    adql = ExoplanetProvider._adql("O'Brien", 5)

    assert "'%O''Brien%'" in adql
    assert "'%O'Brien%'" not in adql


def test_number_and_int_ignore_non_numbers() -> None:
    assert ExoplanetProvider._number(1) == 1.0
    assert ExoplanetProvider._number(0.5) == 0.5
    assert ExoplanetProvider._number("1") is None
    assert ExoplanetProvider._number(True) is None
    assert ExoplanetProvider._number(None) is None

    assert ExoplanetProvider._int(7.0) == 7
    assert ExoplanetProvider._int(0) == 0
    assert ExoplanetProvider._int("7") is None
    assert ExoplanetProvider._int(True) is None
    assert ExoplanetProvider._int(None) is None


def test_measure_trims_trailing_zeros() -> None:
    assert ExoplanetProvider._measure(None, 2, "d") == ""
    assert ExoplanetProvider._measure(6.099043, 2, "d") == "6.1 d"
    assert ExoplanetProvider._measure(205.90, 1, "K") == "205.9 K"
    assert ExoplanetProvider._measure(1134.0, 1, "K") == "1134 K"
    assert ExoplanetProvider._measure(100.0, 2, "d") == "100 d"
    assert ExoplanetProvider._measure(12.4292, 2, "pc") == "12.43 pc"


def test_build_result_skips_nameless_rows() -> None:
    assert _provider()._build_result({"pl_name": ""}) is None
    assert _provider()._build_result({"hostname": "Kepler-16"}) is None


@pytest.mark.asyncio
async def test_search_ranks_exact_name_match_first(respx_mock) -> None:
    _mock_search(
        respx_mock,
        payload=[
            {"pl_name": "Kepler-160 b", "hostname": "Kepler-160"},
            _KEPLER_16_ROW,
        ],
    )

    result = await _provider().search("Kepler-16 b", SearchParams(num_results=10))

    assert [r.title for r in result.results] == ["Kepler-16 b", "Kepler-160 b"]
    assert [r.rank for r in result.results] == [1, 2]


@pytest.mark.asyncio
async def test_search_ranks_host_star_match_over_other_prefixes(respx_mock) -> None:
    _mock_search(
        respx_mock,
        payload=[
            {"pl_name": "Kepler-160 b", "hostname": "Kepler-160"},
            {"pl_name": "Kepler-16 b", "hostname": "Kepler-16"},
        ],
    )

    result = await _provider().search("kepler-16", SearchParams(num_results=10))

    assert [r.title for r in result.results] == ["Kepler-16 b", "Kepler-160 b"]


@pytest.mark.asyncio
async def test_search_builds_the_planet_result(respx_mock) -> None:
    _mock_search(respx_mock)

    result = await _provider().search("TRAPPIST-1 e", SearchParams(num_results=10))
    planet = result.results[0]

    assert planet.title == "TRAPPIST-1 e"
    assert planet.url == (
        "https://exoplanetarchive.ipac.caltech.edu/overview/TRAPPIST-1%20e"
    )
    assert planet.source == "exoplanetarchive.ipac.caltech.edu"
    assert planet.provider == "exoplanet"
    assert planet.published_date is None
    assert planet.snippet == (
        "Host star TRAPPIST-1 | Discovered 2017 via Transit (Spitzer) | "
        "7 planets in system | Period: 6.1 d | Radius: 0.92 Earth radii | "
        "Mass: 0.77 Earth masses | Distance: 12.43 pc | T_eq: 251 K"
    )
    assert planet.extra == {
        "planet": "TRAPPIST-1 e",
        "host_star": "TRAPPIST-1",
        "discovery_year": 2017,
        "discovery_method": "Transit",
        "discovery_facility": "Spitzer",
        "stars_in_system": 1,
        "planets_in_system": 7,
        "orbital_period_days": 6.099043,
        "semi_major_axis_au": 0.02928285,
        "radius_earth": 0.92,
        "mass_earth": 0.772,
        "mass_provenance": "Mass",
        "equilibrium_temp_k": 251.0,
        "distance_pc": 12.4292,
    }


@pytest.mark.asyncio
async def test_search_reports_the_size_of_the_system(respx_mock) -> None:
    _mock_search(respx_mock)

    result = await _provider().search("Kepler-16", SearchParams(num_results=10))
    kepler = next(r for r in result.results if r.title == "Kepler-16 b")
    trappist = next(r for r in result.results if r.title == "TRAPPIST-1 e")

    # Kepler-16 hosts its planet in a binary system; single-star systems
    # carry no star-count part in the snippet.
    assert "2-star system" in kepler.snippet
    assert "planets in system" not in kepler.snippet
    assert kepler.extra["stars_in_system"] == 2
    assert kepler.extra["planets_in_system"] == 1

    assert "7 planets in system" in trappist.snippet
    assert "star system" not in trappist.snippet
    assert trappist.extra["stars_in_system"] == 1
    assert trappist.extra["planets_in_system"] == 7


@pytest.mark.asyncio
async def test_search_sends_the_adql_query(respx_mock) -> None:
    route = _mock_search(respx_mock)

    await _provider().search("  TRAPPIST-1  ", SearchParams(num_results=10))

    assert route.call_count == 1
    params = route.calls[0].request.url.params
    assert params["format"] == "json"
    query = params["query"]
    # 10 requested results are oversampled 3x before local re-ranking.
    assert query.startswith("select top 30 ")
    assert "pl_name like '%TRAPPIST-1%'" in query


@pytest.mark.asyncio
async def test_search_strips_like_metacharacters(respx_mock) -> None:
    route = _mock_search(respx_mock)

    await _provider().search("K%_epler", SearchParams(num_results=5))

    query = route.calls[0].request.url.params["query"]
    assert "'%Kepler%'" in query


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    _mock_search(respx_mock)

    result = await _provider().search("TRAPPIST-1", SearchParams(num_results=1))

    assert [r.title for r in result.results] == ["TRAPPIST-1 e"]
    assert result.results[0].rank == 1


@pytest.mark.asyncio
async def test_search_blank_and_wildcard_queries_skip_requests(respx_mock) -> None:
    route = _mock_search(respx_mock)

    assert (await _provider().search("   ", SearchParams(num_results=5))).results == []
    assert (await _provider().search("%%_", SearchParams(num_results=5))).results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_handles_unexpected_payload_shapes(respx_mock) -> None:
    route = respx_mock.get(_TAP_URL).mock(
        side_effect=[
            respx.MockResponse(200, json={"error": "ORA-00904: invalid identifier"}),
            respx.MockResponse(200, json=[["not", "a", "mapping"], {"pl_name": ""}]),
        ],
    )

    assert (await _provider().search("quic", SearchParams(num_results=5))).results == []
    assert (await _provider().search("quic", SearchParams(num_results=5))).results == []
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_TAP_URL).mock(return_value=respx.MockResponse(400))

    with pytest.raises(HTTPStatusError):
        await _provider().search("trappist", SearchParams(num_results=5))


@pytest.mark.asyncio
async def test_snippet_is_truncated_to_shared_limit(respx_mock) -> None:
    row = dict(_TRAPPIST_ROW, hostname="LongHost" * 60)
    _mock_search(respx_mock, payload=[row])

    result = await _provider().search("LongHost", SearchParams(num_results=5))

    snippet = result.results[0].snippet
    assert len(snippet) == 400
    assert snippet.startswith("Host star LongHostLongHost")
