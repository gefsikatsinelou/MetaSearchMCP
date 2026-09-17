"""Unit tests for the ProPublica Nonprofit Explorer search provider."""

from __future__ import annotations

import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.propublica_nonprofits import (
    ProPublicaNonprofitsProvider,
    _subsection_label,
)

_SEARCH_URL = "https://projects.propublica.org/nonprofits/api/v2/search.json"

_SEARCH_RESPONSE: dict[str, object] = {
    "total_results": 3,
    "organizations": [
        {
            "ein": 581771391,
            "strein": "58-1771391",
            "name": "Red Cross Civitans",
            "sub_name": "Red Cross Civitans Red Cross Inc Nc",
            "city": "Climax",
            "state": "NC",
            "ntee_code": "T30",
            "raw_ntee_code": "T30",
            "subseccd": 4,
            "has_subseccd": True,
            "have_filings": None,
            "have_extracts": None,
            "have_pdfs": None,
            "score": 94.403076,
        },
        {
            "ein": 986001029,
            "strein": "98-6001029",
            "name": "International Committee Of The Red Cross",
            "sub_name": "International Committee Of The Red Cross",
            "city": "Geneva",
            "state": None,
            "ntee_code": "Q33Z",
            "raw_ntee_code": "Q33Z",
            "subseccd": 3,
            "has_subseccd": True,
            "score": 71,
        },
        {
            "ein": 473833780,
            "strein": "47-3833780",
            "name": "",
            "sub_name": "",
            "city": None,
            "state": None,
            "ntee_code": None,
            "raw_ntee_code": None,
            "subseccd": None,
            "has_subseccd": False,
            "score": 1.5,
        },
    ],
    "num_pages": 1,
    "cur_page": 0,
    "page_offset": 0,
    "per_page": 25,
    "search_query": "red cross",
    "api_version": 2,
}

_EMPTY_RESPONSE: dict[str, object] = {
    "total_results": 0,
    "organizations": [],
    "num_pages": 0,
    "cur_page": 0,
    "per_page": 25,
    "search_query": "zzzznotanonprofitxyz",
}


def _provider() -> ProPublicaNonprofitsProvider:
    return ProPublicaNonprofitsProvider()


def test_name_tags_and_description() -> None:
    p = _provider()
    assert p.name == "propublica_nonprofits"
    assert p.tags == ["reference", "nonprofit", "us"]
    assert "No API key required" in p.description


def test_parse_builds_rich_results_in_api_order() -> None:
    result = _provider()._parse(_SEARCH_RESPONSE)

    assert [r.title for r in result.results] == [
        "Red Cross Civitans",
        "International Committee Of The Red Cross",
    ]

    first = result.results[0]
    assert (
        first.url
        == "https://projects.propublica.org/nonprofits/organizations/581771391"
    )
    assert first.source == "projects.propublica.org"
    assert first.provider == "propublica_nonprofits"
    assert first.rank == 1
    assert first.published_date is None
    assert first.snippet == (
        "Location: Climax, NC | "
        "Also known as: Red Cross Civitans Red Cross Inc Nc | "
        "NTEE: T30 (Philanthropy, Voluntarism & Grantmaking Foundations) | "
        "IRS subsection: 501(c)(4) | EIN: 58-1771391"
    )
    assert first.extra == {
        "ein": "581771391",
        "strein": "58-1771391",
        "name": "Red Cross Civitans",
        "sub_name": "Red Cross Civitans Red Cross Inc Nc",
        "city": "Climax",
        "state": "NC",
        "ntee_code": "T30",
        "ntee_category": "Philanthropy, Voluntarism & Grantmaking Foundations",
        "subsection": "501(c)(4)",
        "subsection_code": 4,
        "score": 94.403076,
        "total_results": 3,
        "url": "https://projects.propublica.org/nonprofits/organizations/581771391",
    }


def test_parse_handles_missing_city_state_and_duplicate_sub_name() -> None:
    second = _provider()._parse(_SEARCH_RESPONSE).results[1]

    assert second.rank == 2
    assert second.extra["city"] == "Geneva"
    assert second.extra["state"] is None
    assert second.extra["sub_name"] is None
    assert second.extra["ntee_category"] == (
        "International, Foreign Affairs & National Security"
    )
    assert second.extra["subsection"] == "501(c)(3)"
    assert second.extra["score"] == 71.0
    assert second.snippet == (
        "Location: Geneva | "
        "NTEE: Q33Z (International, Foreign Affairs & National Security) | "
        "IRS subsection: 501(c)(3) | EIN: 98-6001029"
    )


def test_parse_skips_records_without_a_name() -> None:
    result = _provider()._parse(_SEARCH_RESPONSE)

    assert len(result.results) == 2
    assert all(r.title for r in result.results)


def test_parse_falls_back_to_sub_name_and_numeric_ein() -> None:
    record = {"ein": 1234, "sub_name": "Fallback Name", "strein": "junk"}

    only = _provider()._parse({"organizations": [record]}).results[0]

    assert only.title == "Fallback Name"
    assert only.extra["ein"] == "1234"
    assert only.extra["strein"] == "junk"
    assert only.extra["subsection"] is None
    assert only.extra["ntee_code"] is None


def test_parse_uses_home_url_when_no_ein_is_usable() -> None:
    record = {"name": "Nameless EIN Org", "ein": None, "strein": ""}

    only = _provider()._parse({"organizations": [record]}).results[0]

    assert only.extra["ein"] is None
    assert only.url == "https://projects.propublica.org/nonprofits/"
    assert only.snippet == ""


def test_parse_empty_and_malformed_payloads() -> None:
    p = _provider()
    assert p._parse(None).results == []
    assert p._parse([]).results == []
    assert p._parse({}).results == []
    assert p._parse("junk").results == []
    assert p._parse({"organizations": "junk"}).results == []
    assert p._parse({"organizations": [42, "junk", []]}).results == []


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse(_SEARCH_RESPONSE, limit=1).results) == 1
    assert len(p._parse(_SEARCH_RESPONSE, 2).results) == 2


def test_subsection_labels() -> None:
    assert _subsection_label(3) == "501(c)(3)"
    assert _subsection_label(29) == "501(c)(29)"
    assert _subsection_label(92) == "4947(a)(1)"
    assert _subsection_label(0) is None
    assert _subsection_label(30) is None
    assert _subsection_label(None) is None


def test_ntee_major_group_mapping() -> None:
    p = _provider()
    assert p._ntee({"ntee_code": "A20"}) == ("A20", "Arts, Culture & Humanities")
    assert p._ntee({"ntee_code": "W00F"})[1] == "Public & Societal Benefit"
    assert p._ntee({"raw_ntee_code": "B25"})[0] == "B25"
    assert p._ntee({"ntee_code": "?"}) == ("?", None)
    assert p._ntee({}) == ("", None)


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "propublica_nonprofits" in registry
    assert registry["propublica_nonprofits"].tags == ["reference", "nonprofit", "us"]


@pytest.mark.asyncio
async def test_search_queries_the_json_endpoint(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE)
    )

    p = _provider()
    result = await p.search("red cross", SearchParams(num_results=5))

    assert [r.title for r in result.results] == [
        "Red Cross Civitans",
        "International Committee Of The Red Cross",
    ]
    call = respx_mock.calls[0]
    assert call.request.url.params["q"] == "red cross"
    assert call.request.url.params["page"] == "0"


def test_parse_covers_the_full_endpoint_page() -> None:
    many = [{"ein": n + 1000, "name": f"Nonprofit {n}"} for n in range(40)]
    result = _provider()._parse({"organizations": many}, limit=25)

    assert len(result.results) == 25
    assert result.results[-1].rank == 25


@pytest.mark.asyncio
async def test_search_respects_provider_max_results(respx_mock) -> None:
    many = [{"ein": n + 1000, "name": f"Nonprofit {n}"} for n in range(40)]
    respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json={"organizations": many})
    )

    p = _provider()
    result = await p.search("nonprofit", SearchParams(num_results=50))

    assert len(result.results) == p._max_results


@pytest.mark.asyncio
async def test_search_skips_blank_query(respx_mock) -> None:
    route = respx_mock.get(_SEARCH_URL)

    p = _provider()
    result = await p.search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE)
    )

    p = _provider()
    result = await p.search("zzzznotanonprofitxyz", SearchParams(num_results=5))

    assert result.results == []
