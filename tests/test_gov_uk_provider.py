"""Unit tests for the GOV.UK content search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.gov_uk import GovUkProvider

_SAMPLE_RESPONSE = {
    "results": [
        {
            "title": "Climate change",
            "link": "/guidance/climate-change",
            "description": (
                "Advises how to identify suitable mitigation and adaptation "
                "measures in the planning process."
            ),
            "format": "detailed_guide",
            "document_type": "edition",
            "public_timestamp": "2019-03-15T15:03:32Z",
            "organisations": [
                {
                    "title": "Ministry of Housing, Communities and Local Government",
                    "acronym": "MHCLG",
                },
                {"title": "Department for Energy Security and Net Zero"},
            ],
            "world_locations": ["United Kingdom"],
        },
        {
            "title": "Net zero strategy",
            "link": "https://www.gov.uk/government/publications/net-zero-strategy",
            "description": "",
            "format": "publication",
            "public_timestamp": None,
            "organisations": [],
        },
        {
            # Missing title -> skipped.
            "link": "/no-title",
            "description": "x",
        },
        {
            # Missing link -> skipped.
            "title": "No link",
        },
    ]
}


def _provider() -> GovUkProvider:
    return GovUkProvider()


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=10)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Climate change"
    assert r.url == "https://www.gov.uk/guidance/climate-change"
    assert "mitigation and adaptation" in r.snippet
    assert "Format: detailed_guide" in r.snippet
    assert "Organisations: Ministry of Housing, Communities and Local Government" in (
        r.snippet
    )
    assert r.source == "gov.uk"
    assert r.provider == "gov_uk"
    assert r.rank == 1
    assert r.published_date == "2019-03-15"
    assert r.extra["format"] == "detailed_guide"
    assert r.extra["document_type"] == "edition"
    assert r.extra["world_locations"] == ["United Kingdom"]
    assert len(r.extra["organisations"]) == 2


def test_parse_absolute_link_preserved() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=10)
    r = result.results[1]
    assert r.url == "https://www.gov.uk/government/publications/net-zero-strategy"


def test_parse_missing_fields() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=10)
    r = result.results[1]
    # Empty description still yields a string snippet and no date.
    assert isinstance(r.snippet, str)
    assert r.published_date is None
    assert r.extra["organisations"] == []


def test_parse_respects_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1
    assert result.results[0].title == "Climate change"


def test_parse_empty() -> None:
    assert _provider()._parse({"results": []}, limit=10).results == []


def test_parse_non_dict_results() -> None:
    result = _provider()._parse({"results": ["nope", None, 7]}, limit=10)
    assert result.results == []


def test_parse_non_dict_data() -> None:
    assert _provider()._parse("not-a-dict", limit=10).results == []
    assert _provider()._parse({}, limit=10).results == []


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


def test_registered_in_registry() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "gov_uk" in registry
    assert registry["gov_uk"].tags == ["web", "gov", "knowledge"]


@pytest.mark.asyncio
async def test_search_builds_query(respx_mock) -> None:
    import respx

    respx_mock.get("https://www.gov.uk/api/search.json").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("climate change", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "gov_uk"
    request = respx_mock.calls.last.request
    assert request.url.params["q"] == "climate change"
    assert request.url.params["count"] == "5"
