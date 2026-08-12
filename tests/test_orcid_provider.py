"""Unit tests for the ORCID researcher profile search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.orcid import OrcidProvider

_SAMPLE_RESPONSE = {
    "num-found": 39800,
    "expanded-result": [
        {
            "orcid-id": "0000-0002-8925-1337",
            "given-names": "Kevin",
            "family-names": "Davies",
            "credit-name": None,
            "other-name": [],
            "email": [],
            "institution-name": [
                "University of Oxford",
                "Nature Publishing Group",
            ],
        },
        {
            "orcid-id": "0000-0001-9297-5304",
            "given-names": "Blake",
            "family-names": "Wiedenheft",
            "credit-name": "Blake Wiedenheft",
            "other-name": ["B Wiedenheft"],
            "email": [],
            "institution-name": [],
        },
        {
            # Missing orcid-id -> skipped.
            "given-names": "Ghost",
            "family-names": "Researcher",
            "institution-name": [],
        },
    ],
}

_EMPTY_RESPONSE = {"num-found": 0, "expanded-result": []}


def _provider() -> OrcidProvider:
    return OrcidProvider()


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Kevin Davies"
    assert r.url == "https://orcid.org/0000-0002-8925-1337"
    assert "Affiliations: University of Oxford, Nature Publishing Group" in r.snippet
    assert r.source == "orcid.org"
    assert r.provider == "orcid"
    assert r.rank == 1
    assert r.extra["orcid_id"] == "0000-0002-8925-1337"
    assert r.extra["institutions"] == [
        "University of Oxford",
        "Nature Publishing Group",
    ]
    assert r.extra["credit_name"] == ""


def test_parse_credit_name_and_other_names() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    r = result.results[1]
    assert r.title == "Blake Wiedenheft"
    assert r.url == "https://orcid.org/0000-0001-9297-5304"
    assert "Also known as: B Wiedenheft" in r.snippet
    assert "Affiliations" not in r.snippet
    assert r.extra["credit_name"] == "Blake Wiedenheft"
    assert r.extra["given_names"] == "Blake"
    assert r.extra["family_names"] == "Wiedenheft"


def test_parse_empty() -> None:
    result = _provider()._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_parse_missing_orcid_id_skipped() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert all(r.extra["orcid_id"] for r in result.results)


def test_parse_non_list_expanded_result() -> None:
    result = _provider()._parse({"expanded-result": "not-a-list"})
    assert result.results == []


def test_parse_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, max_results=1)
    assert len(result.results) == 1
    assert result.results[0].rank == 1


def test_display_name_prefers_credit_name() -> None:
    p = _provider()
    assert (
        p._display_name(
            {
                "given-names": "John",
                "family-names": "Smith",
                "credit-name": "J. Smith",
            }
        )
        == "J. Smith"
    )
    assert p._display_name({"given-names": "John", "family-names": "Smith"}) == (
        "John Smith"
    )
    assert p._display_name({}) == ""


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_json_accept_header(respx_mock) -> None:
    import respx

    respx_mock.get("https://pub.orcid.org/v3.0/expanded-search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("crispr", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "orcid"
    request = respx_mock.calls.last.request
    assert request.url.params["q"] == "crispr"
    assert request.url.params["rows"] == "5"
    assert request.headers["accept"] == "application/json"
