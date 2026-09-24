"""Unit tests for the OpenStreetMap Overpass feature search provider."""

from __future__ import annotations

import httpx
import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH
from metasearchmcp.providers.overpass import OverpassProvider

_API_URL = "https://overpass-api.de/api/interpreter"

_SAMPLE_RESPONSE: dict[str, object] = {
    "version": 0.6,
    "generator": "Overpass API 0.7.62",
    "elements": [
        {
            "type": "node",
            "id": 123456,
            "lat": 52.52,
            "lon": 13.405,
            "tags": {
                "name": "The Barn Coffee Shop",
                "amenity": "cafe",
                "addr:street": "Auguststraße",
                "addr:housenumber": "58",
                "addr:postcode": "10115",
                "addr:city": "Berlin",
                "opening_hours": "Mo-Fr 08:00-18:00",
                "website": "https://barn.example",
                "phone": "+49 30 123456",
                "brand": "The Barn",
                "wikipedia": "de:The Barn",
            },
        },
        {
            # Ways are queried with "out center": coordinates sit in the
            # center object instead of the element itself.
            "type": "way",
            "id": 987654,
            "center": {"lat": 48.8584, "lon": 2.2945},
            "tags": {
                "name": "Café Tour Eiffel",
                "tourism": "museum",
                "operator": "Ville de Paris",
            },
        },
        {
            "type": "relation",
            "id": 555,
            "center": {"lat": 51.5, "lon": -0.12},
            "tags": {
                "name": "Uncategorised Green",
                "leisure": "park",
                "wikidata": "Q1",
            },
        },
        # Unnamed feature -> skipped.
        {
            "type": "node",
            "id": 42,
            "lat": 1.0,
            "lon": 2.0,
            "tags": {"amenity": "bench"},
        },
        # Duplicate type/id -> collapsed onto the first occurrence.
        {
            "type": "node",
            "id": 123456,
            "lat": 52.52,
            "lon": 13.405,
            "tags": {"name": "The Barn Coffee Shop (duplicate)"},
        },
        # No id -> no feature page, skipped.
        {"type": "node", "tags": {"name": "Nameless id"}},
        # No tags -> skipped.
        {"type": "way", "id": 7},
        "junk",
        None,
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"version": 0.6, "elements": []}

# The public instance answers a query it could not finish in time with a
# remark instead of an error status.
_TIMEOUT_RESPONSE: dict[str, object] = {
    "version": 0.6,
    "remark": 'runtime error: Query timed out in "nwr" at line 3 after 8 seconds.',
    "elements": [],
}


def _provider() -> OverpassProvider:
    return OverpassProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "overpass"
    assert p.tags == ["places", "geo", "web", "maps"]


def test_registered_in_registry() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "overpass" in registry
    assert registry["overpass"].tags == ["places", "geo", "web", "maps"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 3
    r = result.results[0]
    assert r.title == "The Barn Coffee Shop"
    assert r.url == "https://www.openstreetmap.org/node/123456"
    assert r.snippet.startswith("amenity=cafe | Auguststraße 58, 10115 Berlin")
    assert "Hours: Mo-Fr 08:00-18:00" in r.snippet
    assert "The Barn" in r.snippet
    assert "+49 30 123456" in r.snippet
    assert "https://barn.example" in r.snippet
    assert "Coordinates: 52.52000, 13.40500" in r.snippet
    assert len(r.snippet) <= MAX_SNIPPET_LENGTH
    assert r.source == "openstreetmap.org"
    assert r.provider == "overpass"
    assert r.rank == 1
    assert r.extra["osm_type"] == "node"
    assert r.extra["osm_id"] == "123456"
    assert r.extra["category"] == "amenity"
    assert r.extra["category_value"] == "cafe"
    assert r.extra["address"] == "Auguststraße 58, 10115 Berlin"
    assert r.extra["city"] == "Berlin"
    assert r.extra["postcode"] == "10115"
    assert r.extra["opening_hours"] == "Mo-Fr 08:00-18:00"
    assert r.extra["phone"] == "+49 30 123456"
    assert r.extra["website"] == "https://barn.example"
    assert r.extra["brand"] == "The Barn"
    assert r.extra["wikipedia"] == "de:The Barn"
    assert r.extra["lat"] == pytest.approx(52.52)
    assert r.extra["lon"] == pytest.approx(13.405)


def test_parse_way_uses_center_coordinates() -> None:
    r = _provider()._parse(_SAMPLE_RESPONSE).results[1]
    assert r.title == "Café Tour Eiffel"
    assert r.url == "https://www.openstreetmap.org/way/987654"
    assert r.extra["osm_type"] == "way"
    assert r.extra["lat"] == pytest.approx(48.8584)
    assert r.extra["lon"] == pytest.approx(2.2945)
    assert r.extra["operator"] == "Ville de Paris"
    assert r.snippet == (
        "tourism=museum | Ville de Paris | Coordinates: 48.85840, 2.29450"
    )


def test_parse_sparse_relation() -> None:
    r = _provider()._parse(_SAMPLE_RESPONSE).results[2]
    assert r.url == "https://www.openstreetmap.org/relation/555"
    assert r.extra["category"] == "leisure"
    assert r.extra["category_value"] == "park"
    assert r.extra["address"] is None
    assert r.extra["opening_hours"] is None
    assert r.extra["brand"] is None
    assert r.extra["wikidata"] == "Q1"


def test_parse_skips_unnamed_unlinked_and_malformed_elements() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert [r.title for r in result.results] == [
        "The Barn Coffee Shop",
        "Café Tour Eiffel",
        "Uncategorised Green",
    ]
    # The duplicate is dropped, so ranks stay contiguous.
    assert [r.rank for r in result.results] == [1, 2, 3]


def test_parse_limit_and_junk_payloads() -> None:
    p = _provider()
    assert len(p._parse(_SAMPLE_RESPONSE, limit=2).results) == 2
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse(_TIMEOUT_RESPONSE).results == []
    assert p._parse("junk").results == []  # type: ignore[arg-type]
    assert p._parse(None).results == []  # type: ignore[arg-type]
    assert p._parse({}).results == []  # type: ignore[arg-type]
    assert p._parse({"elements": "junk"}).results == []  # type: ignore[arg-type]
    assert p._parse({"elements": [1, "junk", None]}).results == []


def test_element_without_tags_is_skipped() -> None:
    result = _provider()._parse({"elements": [{"type": "node", "id": 1}]})
    assert result.results == []


def test_parse_truncates_long_address() -> None:
    from metasearchmcp.providers.overpass import _SNIPPET_ADDRESS_LENGTH

    street = "Very Long Street Name " * 12
    result = _provider()._parse(
        {
            "elements": [
                {
                    "type": "node",
                    "id": 1,
                    "lat": 1.0,
                    "lon": 2.0,
                    "tags": {"name": "Long address", "addr:street": street},
                }
            ]
        }
    )
    snippet = result.results[0].snippet
    assert len(snippet) <= MAX_SNIPPET_LENGTH
    assert "…" in snippet
    assert snippet.startswith("Very Long Street Name")
    address = result.results[0].extra["address"]
    assert len(address) > _SNIPPET_ADDRESS_LENGTH
    assert address == " ".join(street.split())


def test_pattern_escapes_regex_metacharacters() -> None:
    from metasearchmcp.providers.overpass import _pattern

    assert _pattern("coffee") == "coffee"
    assert _pattern("coffee  shop") == "coffee.*shop"
    assert _pattern("café (berlin)") == "café.*\\(berlin\\)"
    assert _pattern("a.b*c") == "a\\.b\\*c"
    assert _pattern('say "hi"') == 'say.*\\"hi\\"'
    assert _pattern("c++") == "c\\+\\+"


def test_build_query_scopes_to_country() -> None:
    from metasearchmcp.providers.overpass import (
        _QUERY_TIMEOUT_SECONDS,
        _build_query,
    )

    scoped = _build_query("coffee", "DE", 20)
    assert scoped.startswith(f"[out:json][timeout:{_QUERY_TIMEOUT_SECONDS}];\n")
    assert 'area["ISO3166-1"="DE"][admin_level=2]->.searchArea;' in scoped
    assert 'nwr(area.searchArea)["name"~"coffee",i];' in scoped
    assert scoped.endswith("out center 20;")

    global_query = _build_query("coffee", "", 5)
    assert "area[" not in global_query
    assert 'nwr["name"~"coffee",i];' in global_query
    assert global_query.endswith("out center 5;")


def test_area_country_normalization() -> None:
    p = _provider()
    assert p._area_country("de") == "DE"
    assert p._area_country("") == "US"
    assert p._area_country("global") == ""
    assert p._area_country("1234") == ""


def test_address_and_category_helpers() -> None:
    from metasearchmcp.providers.overpass import _address, _category

    assert _address({"addr:street": "Main Street", "addr:housenumber": "5"}) == (
        "Main Street 5",
        "",
        "",
    )
    assert _address({"addr:city": "Berlin", "addr:postcode": "10115"})[0] == (
        "10115 Berlin"
    )
    assert _address({}) == ("", "", "")
    # The first classifying tag in priority order wins.
    assert _category({"shop": "bakery", "amenity": "cafe"}) == ("amenity", "cafe")
    assert _category({"name": "Nothing"}) == ("", "")


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_scoped_query(respx_mock) -> None:
    import respx

    respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search(
        "  coffee   shop  ",
        SearchParams(num_results=5, country="de"),
    )

    assert len(result.results) == 3
    request = respx_mock.calls.last.request
    body = request.url.params["data"]
    # Whitespace in the query is collapsed before the request is sent.
    assert '["name"~"coffee.*shop",i]' in body
    assert 'area["ISO3166-1"="DE"][admin_level=2]->.searchArea;' in body
    assert body.endswith("out center 5;")


@pytest.mark.asyncio
async def test_search_global_when_country_is_not_a_code(respx_mock) -> None:
    import respx

    respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    await p.search("coffee", SearchParams(num_results=5, country="global"))

    body = respx_mock.calls.last.request.url.params["data"]
    assert "area[" not in body
    assert 'nwr["name"~"coffee",i];' in body


@pytest.mark.asyncio
async def test_search_blank_query_makes_no_request(respx_mock) -> None:
    import respx

    route = respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    assert (await p.search("   ", SearchParams(num_results=5))).results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_no_results_returns_empty(respx_mock) -> None:
    import respx

    respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("zzzznotathingqqq", SearchParams(num_results=5))
    assert result.results == []


@pytest.mark.asyncio
async def test_search_query_timeout_returns_empty(respx_mock) -> None:
    import respx

    respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_TIMEOUT_RESPONSE),
    )

    p = _provider()
    result = await p.search("coffee", SearchParams(num_results=5))
    assert result.results == []


@pytest.mark.asyncio
async def test_search_malformed_query_raises(respx_mock) -> None:
    import respx

    # The public instance answers a query it cannot parse with HTTP 400.
    respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(400, text="line 3: parse error"),
    )

    p = _provider()
    with pytest.raises(httpx.HTTPStatusError):
        await p.search("coffee", SearchParams(num_results=5))
