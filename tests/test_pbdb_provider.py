"""Unit tests for the Paleobiology Database (PBDB) fossil-taxon provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.pbdb import PbdbProvider

_API_URL = "https://paleobiodb.org/data1.2/taxa/list.json"

_RESPONSE: dict[str, object] = {
    "elapsed_time": 0.002,
    "records": [
        {
            "oid": "txn:38613",
            "rnk": 5,
            "nam": "Tyrannosaurus",
            "att": "Osborn 1905",
            "nm2": "tyrant lizard",
            "par": "txn:92294",
            "rid": "ref:9259",
            "ext": "0",
            "noc": 85,
            "fea": 83.6,
            "fla": 72.2,
            "lea": 72.2,
            "lla": 66,
            "tei": "Campanian",
            "tli": "Maastrichtian",
            "phl": "Chordata",
            "cll": "Reptilia",
            "odl": "NO_ORDER_SPECIFIED",
            "fml": "Tyrannosauridae",
            "gnl": "Tyrannosaurus",
        },
        # Extant taxon, rank given as a string, no age range.
        {
            "oid": "txn:40901",
            "rnk": "genus",
            "nam": "Homo",
            "att": "Linnaeus 1758",
            "ext": "1",
            "noc": 238,
            "phl": "Chordata",
            "cll": "Mammalia",
            "odl": "Primates",
            "fml": "Hominidae",
            "gnl": "Homo",
        },
        # Synonym flagged as a nomen nudum with an accepted name.
        {
            "oid": "txn:68293",
            "rnk": "genus",
            "nam": "Tyrannosauripus",
            "att": "Lessertisseur 1955",
            "tdf": "nomen nudum",
            "acc": "txn:38613",
            "acn": "Tyrannosaurus",
            "ext": "0",
            "noc": 0,
            "phl": "Chordata",
            "cll": "Reptilia",
            "odl": "NO_ORDER_SPECIFIED",
            "fml": "Tyrannosauridae",
        },
        # Missing name -> skipped.
        {"oid": "txn:1", "rnk": 5, "nam": "", "noc": 1},
        "junk",
        None,
    ],
}

_EMPTY: dict[str, object] = {"elapsed_time": 0.0, "records": []}


def _provider() -> PbdbProvider:
    return PbdbProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "pbdb"
    assert p.tags == ["science", "nature", "reference", "paleontology"]
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "pbdb" in registry
    assert registry["pbdb"].tags == ["science", "nature", "reference", "paleontology"]


def test_rank_label_maps_codes_and_names() -> None:
    assert PbdbProvider._rank_label(5) == "genus"
    assert PbdbProvider._rank_label(25) == "unranked clade"
    assert PbdbProvider._rank_label("genus") == "genus"
    assert PbdbProvider._rank_label("3") == "species"
    assert PbdbProvider._rank_label(999) == ""
    assert PbdbProvider._rank_label(None) == ""
    assert PbdbProvider._rank_label(True) == ""


def test_classification_filters_sentinel_and_gaps() -> None:
    chain = PbdbProvider._classification(
        {
            "phl": "Chordata",
            "cll": "Reptilia",
            "odl": "NO_ORDER_SPECIFIED",
            "fml": "Tyrannosauridae",
            "gnl": "Tyrannosaurus",
        },
    )
    assert chain == "Chordata > Reptilia > Tyrannosauridae > Tyrannosaurus"
    assert PbdbProvider._classification({}) == ""
    # Any NO_*_SPECIFIED sentinel is dropped, not just the order one.
    assert (
        PbdbProvider._classification({"phl": "Chordata", "fml": "NO_FAMILY_SPECIFIED"})
        == "Chordata"
    )


def test_interval_and_age_range() -> None:
    item = {"tei": "Campanian", "tli": "Maastrichtian", "fea": 83.6, "lla": 66}
    assert PbdbProvider._interval(item) == "Campanian-Maastrichtian"
    assert PbdbProvider._age_range(item) == "83.6-66 Ma"
    assert PbdbProvider._interval({"tei": "Cenomanian", "tli": "Cenomanian"}) == (
        "Cenomanian"
    )
    assert PbdbProvider._age_range({}) == ""


def test_parse_builds_results_with_metadata() -> None:
    result = _provider()._parse(_RESPONSE, limit=10)

    assert [r.title for r in result.results] == [
        "Tyrannosaurus",
        "Homo",
        "Tyrannosauripus",
    ]

    first = result.results[0]
    assert first.rank == 1
    assert first.url == ("https://paleobiodb.org/classic/checkTaxonInfo?taxon_no=38613")
    assert first.source == "paleobiodb.org"
    assert first.provider == "pbdb"
    assert "Osborn 1905" in first.snippet
    assert "Rank: genus" in first.snippet
    assert "extinct" in first.snippet
    assert "Chordata > Reptilia > Tyrannosauridae" in first.snippet
    assert "Age: Campanian-Maastrichtian (83.6-66 Ma)" in first.snippet
    assert "Common name: tyrant lizard" in first.snippet
    assert "85 fossil occurrences" in first.snippet
    assert first.extra["taxon_id"] == "38613"
    assert first.extra["rank"] == "genus"
    assert first.extra["authority"] == "Osborn 1905"
    assert first.extra["common_name"] == "tyrant lizard"
    assert first.extra["first_appearance_ma"] == 83.6
    assert first.extra["last_appearance_ma"] == 66
    assert first.extra["early_interval"] == "Campanian"
    assert first.extra["late_interval"] == "Maastrichtian"
    assert first.extra["extinct"] is True
    assert first.extra["occurrences"] == 85
    assert first.extra["taxon_status"] is None
    assert first.extra["accepted_name"] is None

    second = result.results[1]
    assert second.rank == 2
    assert second.extra["rank"] == "genus"
    assert second.extra["extinct"] is False
    assert second.extra["first_appearance_ma"] is None
    assert "extant" in second.snippet

    third = result.results[2]
    assert third.extra["taxon_status"] == "nomen nudum"
    assert third.extra["accepted_name"] == "Tyrannosaurus"
    assert "nomen nudum" in third.snippet
    assert "Synonym of Tyrannosaurus" in third.snippet


def test_parse_handles_junk_and_limits() -> None:
    assert _provider()._parse("junk", limit=5).results == []
    assert _provider()._parse({}, limit=5).results == []
    assert _provider()._parse({"records": "junk"}, limit=5).results == []

    limited = _provider()._parse(_RESPONSE, limit=1)
    assert len(limited.results) == 1
    assert limited.results[0].title == "Tyrannosaurus"


def test_snippet_is_truncated_to_shared_limit() -> None:
    long_name = "word " * 200
    data = {
        "records": [
            {
                "oid": "txn:42",
                "rnk": 3,
                "nam": long_name.strip(),
                "att": "Someone 2020",
                "noc": 1,
            },
        ],
    }
    result = _provider()._parse(data, limit=5)
    assert len(result.results[0].snippet) <= 400


@pytest.mark.asyncio
async def test_search_sends_base_name_filter(respx_mock) -> None:
    import respx

    route = respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_RESPONSE),
    )

    result = await _provider().search("tyrannosaurus", SearchParams(num_results=4))

    assert [r.title for r in result.results][:2] == ["Tyrannosaurus", "Homo"]
    assert route.call_count == 1
    params = route.calls[0].request.url.params
    assert params["base_name"] == "tyrannosaurus"
    assert params["limit"] == "4"
    assert params["show"] == "attr,app,class,common"


@pytest.mark.asyncio
async def test_search_falls_back_to_name_prefix(respx_mock) -> None:
    import respx

    def responder(request):
        if "base_name" in request.url.params:
            return respx.MockResponse(200, json=_EMPTY)
        return respx.MockResponse(200, json=_RESPONSE)

    route = respx_mock.get(_API_URL).mock(side_effect=responder)

    result = await _provider().search("tyranno", SearchParams(num_results=5))

    assert [r.title for r in result.results][:2] == ["Tyrannosaurus", "Homo"]
    assert route.call_count == 2
    assert route.calls[0].request.url.params["base_name"] == "tyranno"
    assert route.calls[1].request.url.params["name"] == "tyranno%"


@pytest.mark.asyncio
async def test_search_strips_user_wildcards(respx_mock) -> None:
    import respx

    route = respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_RESPONSE),
    )

    await _provider().search("  dino%  ", SearchParams(num_results=5))

    assert route.calls[0].request.url.params["base_name"] == "dino"


@pytest.mark.asyncio
async def test_search_with_blank_query_returns_empty(respx_mock) -> None:
    import respx

    route = respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_RESPONSE),
    )

    result = await _provider().search("   %  ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_tolerates_non_json_response(respx_mock) -> None:
    import respx

    respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(
            200,
            text="<html><body>maintenance</body></html>",
            headers={"Content-Type": "text/html"},
        ),
    )

    result = await _provider().search("dinosaur", SearchParams(num_results=5))

    assert result.results == []
