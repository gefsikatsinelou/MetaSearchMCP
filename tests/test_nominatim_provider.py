"""Unit tests for the OpenStreetMap Nominatim places search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.nominatim import NominatimProvider

_SAMPLE_RESPONSE = [
    {
        "place_id": 310612878,
        "osm_type": "way",
        "osm_id": 81816215,
        "display_name": (
            "Eiffel Tower, Quai Branly, 7th arrondissement of Paris, Paris, France"
        ),
        "category": "tourism",
        "type": "attraction",
        "lat": "48.8582602",
        "lon": "2.2944925",
        "boundingbox": ["48.8578800", "48.8586400", "2.2936700", "2.2953000"],
    },
    {
        "osm_type": "node",
        "osm_id": 123,
        "display_name": "",
        "category": "place",
        "type": "city",
    },
    {
        "place_id": 310000001,
        "osm_type": "relation",
        "osm_id": 7444,
        "display_name": "Paris, Île-de-France, Metropolitan France, 75056, France",
        "category": "boundary",
        "type": "administrative",
        "lat": "48.856614",
        "lon": "2.352222",
    },
]

_EMPTY_RESPONSE: list[object] = []


def test_nominatim_parse_basic():
    p = NominatimProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == (
        "Eiffel Tower, Quai Branly, 7th arrondissement of Paris, Paris, France"
    )
    assert r.url == "https://www.openstreetmap.org/way/81816215"
    assert r.source == "openstreetmap.org"
    assert r.provider == "nominatim"
    assert r.rank == 1
    assert "Category: tourism" in r.snippet
    assert "Type: attraction" in r.snippet
    assert "Coordinates: 48.8582602, 2.2944925" in r.snippet
    assert "BBox:" in r.snippet
    assert r.extra["osm_type"] == "way"
    assert r.extra["osm_id"] == "81816215"
    assert r.extra["lat"] == "48.8582602"
    assert r.extra["lon"] == "2.2944925"


def test_nominatim_parse_skips_item_without_name():
    p = NominatimProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    assert len(result.results) == 2
    assert all(r.title for r in result.results)
    # The second item (Paris) has a valid display name.
    assert result.results[1].title.startswith("Paris")


def test_nominatim_parse_empty():
    p = NominatimProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_nominatim_parse_non_list():
    p = NominatimProvider()
    result = p._parse({"error": "bad"})
    assert result.results == []


def test_nominatim_parse_respects_limit():
    p = NominatimProvider()
    result = p._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1
    assert result.results[0].rank == 1


def test_nominatim_bbox_string():
    assert NominatimProvider._bbox_string([1, 2, 3, 4]) == "1, 2, 3, 4"
    assert NominatimProvider._bbox_string([1, 2]) == ""
    assert NominatimProvider._bbox_string(None) == ""
    assert NominatimProvider._bbox_string("nope") == ""


def test_nominatim_is_available():
    """Keyless provider is always available."""
    assert NominatimProvider().is_available() is True


@pytest.mark.asyncio
async def test_nominatim_search_hits_api_and_parses(respx_mock):
    """The search method hits the Nominatim endpoint and parses the response."""
    import respx

    respx_mock.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = NominatimProvider()
    result = await p.search("eiffel tower", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "nominatim"
    assert result.results[0].title.startswith("Eiffel Tower")


@pytest.mark.asyncio
async def test_nominatim_search_truncates_to_limit(respx_mock):
    """The search method truncates results to the requested limit."""
    import respx

    respx_mock.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = NominatimProvider()
    result = await p.search("eiffel tower", SearchParams(num_results=1))

    assert len(result.results) == 1
    assert result.results[0].title.startswith("Eiffel Tower")


@pytest.mark.asyncio
async def test_nominatim_search_passes_query_param(respx_mock):
    """The search method forwards the query as the q parameter."""
    import respx

    route = respx_mock.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = NominatimProvider()
    await p.search("champs-elysees", SearchParams(num_results=3))

    request = route.calls.last.request
    assert request.url.params["q"] == "champs-elysees"
    assert request.url.params["format"] == "jsonv2"
