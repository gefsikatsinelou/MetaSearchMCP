"""Unit tests for the GLEIF Legal Entity Identifier provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.gleif import GleifProvider

_SAMPLE_RESPONSE: dict[str, object] = {
    "meta": {"pagination": {"total": 2}},
    "data": [
        {
            "type": "lei-records",
            "id": "6488000AOMRUL4037J06",
            "attributes": {
                "lei": "6488000AOMRUL4037J06",
                "entity": {
                    "legalName": {"name": "APPLE FABRICS", "language": "en"},
                    "legalAddress": {
                        "city": "Navsari",
                        "country": "IN",
                        "postalCode": "396415",
                    },
                    "jurisdiction": "IN",
                    "category": "GENERAL",
                    "legalForm": {"id": "A0PS", "other": None},
                    "status": "ACTIVE",
                    "creationDate": "2024-08-31T00:00:00Z",
                },
                "registration": {"status": "ISSUED"},
            },
        },
        {
            # Minimal record: address/legal form missing.
            "type": "lei-records",
            "id": "529900T8BM49AURSDO55",
            "attributes": {
                "lei": "529900T8BM49AURSDO55",
                "entity": {
                    "legalName": {"name": "Apple Inc.", "language": "en"},
                    "status": "INACTIVE",
                    "jurisdiction": "US-DE",
                },
            },
        },
        {
            # Missing entity -> skipped.
            "type": "lei-records",
            "id": "X",
            "attributes": {"lei": "X"},
        },
        {
            # Missing legal name -> skipped.
            "type": "lei-records",
            "id": "Y",
            "attributes": {"lei": "Y", "entity": {"status": "ACTIVE"}},
        },
        "junk",
        None,
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"meta": {}, "data": []}


def _provider() -> GleifProvider:
    return GleifProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "gleif"
    assert p.tags == ["finance", "legal", "business", "web", "reference"]
    assert p.description


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "APPLE FABRICS"
    assert r.url == ("https://search.gleif.org/#/record/6488000AOMRUL4037J06")
    assert r.source == "gleif.org"
    assert r.provider == "gleif"
    assert r.rank == 1
    assert r.published_date == "2024-08-31"
    assert "Status: ACTIVE" in r.snippet
    assert "Jurisdiction: IN" in r.snippet
    assert "Address: Navsari, IN" in r.snippet
    assert "LEI: 6488000AOMRUL4037J06" in r.snippet
    assert r.extra["lei"] == "6488000AOMRUL4037J06"
    assert r.extra["status"] == "ACTIVE"
    assert r.extra["jurisdiction"] == "IN"
    assert r.extra["country"] == "IN"
    assert r.extra["category"] == "GENERAL"
    assert r.extra["legal_form"] == "A0PS"


def test_parse_minimal_record() -> None:
    r = _provider()._parse(_SAMPLE_RESPONSE).results[1]
    assert r.title == "Apple Inc."
    assert r.extra["status"] == "INACTIVE"
    assert r.extra["jurisdiction"] == "US-DE"
    assert r.extra["country"] == ""
    assert r.extra["legal_form"] == ""
    assert r.published_date is None
    # No address -> snippet has no Address segment.
    assert "Address:" not in r.snippet


def test_parse_skips_incomplete_records() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert len(result.results) == 2
    assert all(r.title and r.url and r.extra["lei"] for r in result.results)


def test_parse_limit_and_empty() -> None:
    p = _provider()
    assert len(p._parse(_SAMPLE_RESPONSE, limit=1).results) == 1
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse("junk").results == []  # type: ignore[arg-type]
    assert p._parse(None).results == []  # type: ignore[arg-type]
    assert p._parse({}).results == []  # type: ignore[arg-type]
    assert p._parse({"data": "nope"}).results == []  # type: ignore[arg-type]


def test_parse_snippet_capped_at_shared_limit() -> None:
    from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH

    long_name = "x" * (MAX_SNIPPET_LENGTH + 200)
    result = _provider()._parse(
        {
            "data": [
                {
                    "attributes": {
                        "lei": "ABCDEFGHIJKLMNOPQRST",
                        "entity": {
                            "legalName": {"name": "Name"},
                            "category": long_name,
                            "status": "ACTIVE",
                        },
                    }
                }
            ]
        }
    )
    assert len(result.results[0].snippet) == MAX_SNIPPET_LENGTH


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_query(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.gleif.org/api/v1/lei-records").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("apple", SearchParams(num_results=5))

    assert len(result.results) == 2
    request = respx_mock.calls.last.request
    assert request.url.params["filter[entity.legalName]"] == "apple"
    assert request.url.params["page[size]"] == "5"


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.gleif.org/api/v1/lei-records").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("no-such-entity-xyz", SearchParams(num_results=5))
    assert result.results == []
