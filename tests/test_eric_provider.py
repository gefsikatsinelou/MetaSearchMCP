"""Unit tests for the ERIC education research provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.eric import EricProvider

_SEARCH_URL = "https://api.ies.ed.gov/eric/"

_PAYLOAD = {
    "response": {
        "numFound": 4,
        "start": 0,
        "docs": [
            {
                "id": "EJ1296630",
                "title": "The Science of Reading Comprehension Instruction",
                "author": [
                    "Duke, Nell K.",
                    "Ward, Alessandra E.",
                    "Pearson, P. David",
                ],
                "source": "The Reading Teacher",
                "description": (
                    "Decades of research offer important understandings about "
                    "comprehension &amp; instruction."
                ),
                "subject": [
                    "Reading Comprehension",
                    "Reading Instruction",
                    "Educational Research",
                    "Teaching Methods",
                    "Reading Achievement",
                    "Extra Subject",
                ],
                "publicationtype": [
                    "Journal Articles",
                    "Reports - Descriptive",
                ],
                "publicationdateyear": 2021,
                "peerreviewed": "T",
                "educationlevel": [
                    "Elementary Education",
                    "Early Childhood Education",
                    "Grade 3",
                    "Grade 4",
                ],
                "issn": ["ISSN-0034-0561"],
                "url": "https://www.wiley.com/en-us",
                "language": ["English"],
            },
            {
                "id": "ED385437",
                "title": "Algebra Initiative Colloquium",
                "author": "not-a-list",
                "source": None,
                "description": "",
                "subject": None,
                "publicationtype": [],
                "publicationdateyear": None,
                "peerreviewed": "F",
                "educationlevel": "not-a-list",
                "issn": None,
                "url": None,
                "language": None,
            },
            {"id": "EJ9999999", "description": "Skipped: no title"},
            {"title": "Skipped: no id"},
            "not-a-mapping",
        ],
    },
}


def _mock(respx_mock, payload: object = _PAYLOAD):
    """Mock the ERIC search endpoint with *payload*."""
    return respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=payload),
    )


def _provider() -> EricProvider:
    """Return a fresh provider instance for each test."""
    return EricProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "eric"
    assert p.tags == ["academic", "education", "web"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "eric" in registry
    assert registry["eric"].tags == ["academic", "education", "web"]


@pytest.mark.asyncio
async def test_search_builds_structured_result(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("reading", SearchParams(num_results=10))
    record = result.results[0]

    assert record.title == "The Science of Reading Comprehension Instruction"
    assert record.url == "https://eric.ed.gov/?id=EJ1296630"
    assert record.source == "eric.ed.gov"
    assert record.provider == "eric"
    assert record.rank == 1
    assert record.published_date == "2021"
    assert record.snippet == (
        "Decades of research offer important understandings about "
        "comprehension & instruction. | "
        "Source: The Reading Teacher | "
        "Type: Journal Articles, Reports - Descriptive | "
        "Subjects: Reading Comprehension, Reading Instruction, "
        "Educational Research, Teaching Methods, Reading Achievement | "
        "Education level: Elementary Education, Early Childhood Education, "
        "Grade 3 | Peer reviewed"
    )
    assert record.extra == {
        "id": "EJ1296630",
        "authors": [
            "Duke, Nell K.",
            "Ward, Alessandra E.",
            "Pearson, P. David",
        ],
        "journal": "The Reading Teacher",
        "publication_types": ["Journal Articles", "Reports - Descriptive"],
        "subjects": [
            "Reading Comprehension",
            "Reading Instruction",
            "Educational Research",
            "Teaching Methods",
            "Reading Achievement",
        ],
        "education_levels": [
            "Elementary Education",
            "Early Childhood Education",
            "Grade 3",
        ],
        "peer_reviewed": True,
        "issn": "ISSN-0034-0561",
        "language": ["English"],
        "publisher_url": "https://www.wiley.com/en-us",
    }


@pytest.mark.asyncio
async def test_search_degrades_on_missing_fields(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("algebra", SearchParams(num_results=10))
    second = result.results[1]

    assert second.url == "https://eric.ed.gov/?id=ED385437"
    assert second.rank == 2
    assert second.snippet == ""
    assert second.published_date is None
    # Malformed / absent fields degrade to empty values.
    assert second.extra["authors"] == []
    assert second.extra["journal"] is None
    assert second.extra["subjects"] == []
    assert second.extra["education_levels"] == []
    assert second.extra["peer_reviewed"] is False
    assert second.extra["issn"] is None
    assert second.extra["language"] == []
    assert second.extra["publisher_url"] is None


@pytest.mark.asyncio
async def test_search_skips_incomplete_and_malformed_entries(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("reading", SearchParams(num_results=10))

    assert [r.title for r in result.results] == [
        "The Science of Reading Comprehension Instruction",
        "Algebra Initiative Colloquium",
    ]
    assert [r.rank for r in result.results] == [1, 2]


@pytest.mark.asyncio
async def test_search_deduplicates_by_accession_id(respx_mock) -> None:
    duplicate = {"id": "EJ1", "title": "Same record"}
    _mock(
        respx_mock,
        {"response": {"docs": [duplicate, dict(duplicate)]}},
    )

    result = await _provider().search("same", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["Same record"]


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    _mock(respx_mock)

    result = await _provider().search("reading", SearchParams(num_results=1))

    assert [r.title for r in result.results] == [
        "The Science of Reading Comprehension Instruction",
    ]


@pytest.mark.asyncio
async def test_search_sends_query_params(respx_mock) -> None:
    route = _mock(respx_mock)

    await _provider().search("reading comprehension", SearchParams(num_results=7))

    params = route.calls.last.request.url.params
    assert params["search"] == "reading comprehension"
    assert params["format"] == "json"
    assert params["rows"] == "7"
    assert "id" in params["fields"]


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    route = _mock(respx_mock)

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_handles_unexpected_payload_shapes(respx_mock) -> None:
    for payload in (
        ["not", "a", "mapping"],
        {},
        {"response": None},
        {"response": {"docs": None}},
        {"response": {"docs": "nope"}},
    ):
        respx_mock.get(_SEARCH_URL).mock(
            return_value=respx.MockResponse(200, json=payload),
        )
        result = await _provider().search("reading", SearchParams(num_results=5))
        assert result.results == []


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("reading", SearchParams(num_results=5))
