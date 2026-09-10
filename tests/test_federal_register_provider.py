"""Unit tests for the U.S. Federal Register document provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.federal_register import FederalRegisterProvider

_SAMPLE_RESPONSE: dict[str, object] = {
    "count": 3,
    "results": [
        {
            "title": "Rescission of Climate-Related Disclosure Rules",
            "html_url": (
                "https://www.federalregister.gov/documents/2026/06/03/"
                "2026-11091/rescission-of-climate-related-disclosure-rules"
            ),
            "publication_date": "2026-06-03",
            "abstract": (
                "The Securities and Exchange Commission proposes to rescind "
                "amendments to its rules that require registrants to provide "
                "certain climate-related information."
            ),
            "type": "Proposed Rule",
            "agencies": [
                {"name": "Securities and Exchange Commission", "id": 466},
            ],
            "document_number": "2026-11091",
        },
        {
            # No abstract, multiple agencies.
            "title": "Notice of Public Meeting",
            "html_url": (
                "https://www.federalregister.gov/documents/2026/06/04/"
                "2026-11999/notice-of-public-meeting"
            ),
            "publication_date": "2026-06-04",
            "type": "Notice",
            "agencies": [
                {"name": "Department of Energy"},
                {"name": "Federal Energy Regulatory Commission"},
            ],
            "document_number": "2026-11999",
        },
        {
            # No title -> skipped.
            "html_url": "https://www.federalregister.gov/documents/x",
        },
        {
            # No url -> skipped.
            "title": "Orphan record",
        },
        "junk",
        None,
    ],
}

_EMPTY_RESPONSE: dict[str, object] = {"count": 0, "results": []}


def _provider() -> FederalRegisterProvider:
    return FederalRegisterProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "federal_register"
    assert p.tags == ["legal", "gov", "web"]
    assert p.description


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Rescission of Climate-Related Disclosure Rules"
    assert r.url.endswith("2026-11091/rescission-of-climate-related-disclosure-rules")
    assert r.source == "federalregister.gov"
    assert r.provider == "federal_register"
    assert r.rank == 1
    assert r.published_date == "2026-06-03"
    assert "Securities and Exchange Commission proposes" in r.snippet
    assert "Proposed Rule" in r.snippet
    assert "Agencies: Securities and Exchange Commission" in r.snippet
    assert r.extra["document_number"] == "2026-11091"
    assert r.extra["type"] == "Proposed Rule"
    assert r.extra["agencies"] == ["Securities and Exchange Commission"]


def test_parse_second_document_multiple_agencies() -> None:
    r = _provider()._parse(_SAMPLE_RESPONSE).results[1]
    assert r.title == "Notice of Public Meeting"
    assert r.published_date == "2026-06-04"
    assert r.extra["type"] == "Notice"
    assert r.extra["agencies"] == [
        "Department of Energy",
        "Federal Energy Regulatory Commission",
    ]
    assert r.extra["abstract"] == ""
    # No abstract -> the snippet starts with the type.
    assert r.snippet.startswith("Notice")


def test_parse_skips_incomplete_records() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert len(result.results) == 2
    assert all(r.title and r.url for r in result.results)


def test_parse_limit_and_empty() -> None:
    p = _provider()
    assert len(p._parse(_SAMPLE_RESPONSE, limit=1).results) == 1
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse("junk").results == []  # type: ignore[arg-type]
    assert p._parse(None).results == []  # type: ignore[arg-type]
    assert p._parse({}).results == []  # type: ignore[arg-type]
    assert p._parse({"results": "nope"}).results == []  # type: ignore[arg-type]


def test_parse_snippet_capped_at_shared_limit() -> None:
    from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH

    long_text = "x" * (MAX_SNIPPET_LENGTH + 200)
    result = _provider()._parse(
        {
            "results": [
                {
                    "title": "Long",
                    "html_url": "https://www.federalregister.gov/documents/long",
                    "abstract": long_text,
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

    respx_mock.get("https://www.federalregister.gov/api/v1/documents.json").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("climate disclosure", SearchParams(num_results=5))

    assert len(result.results) == 2
    request = respx_mock.calls.last.request
    assert request.url.params["conditions[term]"] == "climate disclosure"
    assert request.url.params["per_page"] == "5"
    assert request.url.params["order"] == "relevance"
    assert "title" in request.url.params.get_list("fields[]")


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://www.federalregister.gov/api/v1/documents.json").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("no-such-document-xyz", SearchParams(num_results=5))
    assert result.results == []
