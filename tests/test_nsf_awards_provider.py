"""Unit tests for the NSF award search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH
from metasearchmcp.providers.nsf_awards import NsfAwardsProvider

_SAMPLE_RESPONSE: dict[str, object] = {
    "response": {
        "award": [
            {
                "id": "2617572",
                "title": (
                    "Seafloor Phosphorus Weathering and Earth System Response "
                    "to Geologic Perturbations"
                ),
                "abstractText": (
                    "This project examines how phosphorus released during the "
                    "reaction of seawater with basalt drives Earth system change."
                ),
                "awardeeName": "Pennsylvania State Univ University Park",
                "awardeeCity": "UNIVERSITY PARK",
                "awardeeStateCode": "PA",
                "awardeeCountryCode": "US",
                "ueiNumber": "NPM2J7MSCF61",
                "pi": ["Kimberly V Lau kvlau@psu.edu"],
                "coPDPI": [
                    "Bradford J Foley bjf5382@psu.edu",
                    "David A Kubarek dak207@psu.edu",
                ],
                "program": "Critical Minerals & Materials",
                "fundProgramName": "NSF CriticalMinerals&Materials",
                "orgLongName": "Directorate for Geosciences",
                "orgLongName2": "Division Of Earth Sciences",
                "fundsObligatedAmt": "494304",
                "estimatedTotalAmt": "988608",
                "fundsObligated": ["FY 2026 = $494,304.00"],
                "startDate": "06/01/2027",
                "expDate": "05/31/2030",
                "date": "08/05/2026",
                "activeAwd": "true",
                "transType": "Standard Grant",
                "cfdaNumber": "47.050",
                "poName": "Yurena Yanes",
            },
            {
                # No award id -> fallback search URL; sparse record.
                "title": "REU Site: Interdisciplinary Research Experiences",
                "awardee": "UNIVERSITY OF EXAMPLE",
                "awardeeCity": "BOSTON",
                "awardeeStateCode": "MA",
                "transType": "Continuing grant",
            },
            {
                # Missing title -> skipped.
                "id": "9999999",
                "abstractText": "No title here",
            },
            {
                # Duplicate award id -> collapsed onto the first occurrence.
                "id": "2617572",
                "title": "Seafloor Phosphorus Weathering (duplicate)",
            },
            "junk",
            None,
        ],
        "metadata": {"offset": 0, "rpp": 10, "totalCount": 10000},
    }
}

_EMPTY_RESPONSE: dict[str, object] = {
    "response": {
        "award": [],
        "metadata": {"offset": 0, "rpp": 10, "totalCount": 0},
    }
}

# The API answers a query it cannot parse with a fatal service notification
# instead of an HTTP error status.
_FATAL_RESPONSE: dict[str, object] = {
    "response": {
        "serviceNotification": [
            {
                "notificationType": "FATAL",
                "notificationCode": "AwardAPI-004",
                "notificationMessage": "There was an error processing your request.",
            }
        ]
    }
}


def _provider() -> NsfAwardsProvider:
    return NsfAwardsProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "nsf_awards"
    assert p.tags == ["academic", "gov", "science", "funding"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == (
        "Seafloor Phosphorus Weathering and Earth System Response to Geologic "
        "Perturbations"
    )
    assert r.url == "https://www.nsf.gov/awardsearch/show-award/?AWD_ID=2617572"
    assert r.snippet.startswith("Kimberly V Lau | ")
    assert "Awardee: Pennsylvania State Univ University Park, UNIVERSITY PARK, PA" in (
        r.snippet
    )
    assert "Critical Minerals & Materials" in r.snippet
    assert "Division Of Earth Sciences" in r.snippet
    assert "Award: $494,304" in r.snippet
    assert "Project period: 2027-06-01 to 2030-05-31" in r.snippet
    assert "Standard Grant" in r.snippet
    assert "Abstract: This project examines" in r.snippet
    assert len(r.snippet) <= MAX_SNIPPET_LENGTH
    assert r.source == "nsf.gov"
    assert r.provider == "nsf_awards"
    assert r.rank == 1
    assert r.published_date == "2027-06-01"
    assert r.extra["award_id"] == "2617572"
    assert r.extra["awardee"] == "Pennsylvania State Univ University Park"
    assert r.extra["awardee_location"] == "UNIVERSITY PARK, PA"
    assert r.extra["awardee_uei"] == "NPM2J7MSCF61"
    assert r.extra["program"] == "Critical Minerals & Materials"
    assert r.extra["directorate"] == "Directorate for Geosciences"
    assert r.extra["division"] == "Division Of Earth Sciences"
    assert r.extra["funds_obligated"] == 494304
    assert r.extra["estimated_total_amount"] == 988608
    assert r.extra["funds_obligated_by_year"] == ["FY 2026 = $494,304.00"]
    assert r.extra["start_date"] == "2027-06-01"
    assert r.extra["end_date"] == "2030-05-31"
    assert r.extra["active"] is True
    assert r.extra["award_type"] == "Standard Grant"
    assert r.extra["cfda_number"] == "47.050"
    assert r.extra["program_officer"] == "Yurena Yanes"
    assert r.extra["total_results"] == 10000


def test_parse_strips_emails_from_investigators() -> None:
    r = _provider()._parse(_SAMPLE_RESPONSE).results[0]
    assert r.extra["principal_investigators"] == ["Kimberly V Lau"]
    assert r.extra["co_principal_investigators"] == [
        "Bradford J Foley",
        "David A Kubarek",
    ]


def test_parse_sparse_record() -> None:
    r = _provider()._parse(_SAMPLE_RESPONSE).results[1]
    assert r.url.startswith(
        "https://www.nsf.gov/awardsearch/search-results/?QueryText="
    )
    assert "REU+Site" in r.url
    assert r.published_date is None
    assert r.extra["award_id"] is None
    assert r.extra["awardee"] == "UNIVERSITY OF EXAMPLE"
    assert r.extra["awardee_location"] == "BOSTON, MA"
    assert r.extra["funds_obligated"] is None
    assert r.extra["estimated_total_amount"] is None
    assert r.extra["funds_obligated_by_year"] == []
    assert r.extra["active"] is None
    assert r.extra["abstract"] is None
    assert "Continuing grant" in r.snippet


def test_parse_skips_nameless_and_non_dict_items() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert [r.title for r in result.results] == [
        (
            "Seafloor Phosphorus Weathering and Earth System Response to Geologic "
            "Perturbations"
        ),
        "REU Site: Interdisciplinary Research Experiences",
    ]
    # The duplicate award id is dropped, so ranks stay contiguous.
    assert [r.rank for r in result.results] == [1, 2]


def test_parse_limit_and_junk_payloads() -> None:
    p = _provider()
    assert len(p._parse(_SAMPLE_RESPONSE, limit=1).results) == 1
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse(_FATAL_RESPONSE).results == []
    assert p._parse("junk").results == []  # type: ignore[arg-type]
    assert p._parse(None).results == []  # type: ignore[arg-type]
    assert p._parse({}).results == []  # type: ignore[arg-type]
    assert p._parse({"response": {"award": "junk"}}).results == []  # type: ignore[arg-type]
    assert p._parse({"response": []}).results == []  # type: ignore[arg-type]


def test_missing_metadata_leaves_total_unset() -> None:
    result = _provider()._parse({"response": {"award": [{"id": "1", "title": "T"}]}})
    assert result.results[0].extra["total_results"] is None


def test_parse_truncates_long_programme_listing() -> None:
    from metasearchmcp.providers.nsf_awards import _SNIPPET_PROGRAM_LENGTH

    program = ", ".join(f"Programme {n}" for n in range(20))
    result = _provider()._parse(
        {
            "response": {
                "award": [{"id": "1", "title": "Many programmes", "program": program}]
            }
        }
    )
    r = result.results[0]
    # The snippet keeps a readable programme prefix while ``extra`` keeps it all.
    assert r.snippet.startswith(f"{program[: _SNIPPET_PROGRAM_LENGTH - 1].rstrip()}…")
    assert len(r.snippet) <= _SNIPPET_PROGRAM_LENGTH
    assert r.extra["program"] == program


def test_parse_truncates_long_abstract() -> None:
    from metasearchmcp.providers.nsf_awards import _SNIPPET_ABSTRACT_LENGTH

    result = _provider()._parse(
        {
            "response": {
                "award": [
                    {
                        "id": "1",
                        "title": "Long abstract award",
                        "abstractText": "x" * (MAX_SNIPPET_LENGTH + 200),
                    }
                ]
            }
        }
    )
    snippet = result.results[0].snippet
    # A title, abstract and nothing else: the excerpt fills the snippet.
    assert snippet == f"Abstract: {'x' * _SNIPPET_ABSTRACT_LENGTH}"
    assert len(snippet) <= MAX_SNIPPET_LENGTH


def test_iso_date_parsing() -> None:
    from metasearchmcp.providers.nsf_awards import _iso_date

    assert _iso_date("06/01/2027") == "2027-06-01"
    assert _iso_date("1/5/2027") == "2027-01-05"
    assert _iso_date("2027-06-01T00:00:00Z") == "2027-06-01"
    assert _iso_date("13/01/2027") is None
    assert _iso_date("") is None
    assert _iso_date(None) is None
    assert _iso_date("not a date") is None


def test_money_formatting() -> None:
    from metasearchmcp.providers.nsf_awards import _amount, _money

    assert _money("494304") == "$494,304"
    assert _money(494304) == "$494,304"
    assert _money("1,234.00") == "$1,234"
    assert _money("") == ""
    assert _money(None) == ""
    assert _money("n/a") == ""
    assert _money(True) == ""
    assert _amount("n/a") is None


def test_investigator_helper_ignores_junk() -> None:
    from metasearchmcp.providers.nsf_awards import _people

    assert _people("Kimberly V Lau kvlau@psu.edu") == ["Kimberly V Lau"]
    assert _people(["A a@x.org", "A a@x.org"]) == ["A"]
    assert _people(None) == []
    assert _people(123) == []
    assert _people(["  ,;  "]) == []


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_keyword_and_limit(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.nsf.gov/services/v1/awards.json").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("  graphene   oxide  ", SearchParams(num_results=5))

    assert len(result.results) == 2
    request = respx_mock.calls.last.request
    # Whitespace in the query is collapsed before the request is sent.
    assert request.url.params["keyword"] == "graphene oxide"
    assert request.url.params["rpp"] == "5"
    assert request.url.params["offset"] == "0"


@pytest.mark.asyncio
async def test_search_blank_query_makes_no_request(respx_mock) -> None:
    import respx

    route = respx_mock.get("https://api.nsf.gov/services/v1/awards.json").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    assert (await p.search("   ", SearchParams(num_results=5))).results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_no_results_returns_empty(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.nsf.gov/services/v1/awards.json").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("zzzznotathingqqq", SearchParams(num_results=5))
    assert result.results == []


@pytest.mark.asyncio
async def test_search_fatal_notification_returns_empty(respx_mock) -> None:
    import respx

    # An unparseable query is answered with HTTP 200 and a fatal notification.
    respx_mock.get("https://api.nsf.gov/services/v1/awards.json").mock(
        return_value=respx.MockResponse(200, json=_FATAL_RESPONSE),
    )

    p = _provider()
    result = await p.search("[climate]", SearchParams(num_results=5))
    assert result.results == []
