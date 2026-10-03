"""Unit tests for the MedlinePlus consumer health topic search provider."""

# ruff: noqa: E501

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.medlineplus import MedlinePlusProvider

_API_URL = "https://wsearch.nlm.nih.gov/ws/query"

_XML = """<?xml version="1.0" encoding="UTF-8"?>
<nlmSearchResult>
  <term>asthma</term>
  <count>3</count>
  <list num="3" start="0" per="3">
    <document rank="1" url="https://medlineplus.gov/asthma.html">
      <content name="title">&lt;span class="qt0"&gt;Asthma&lt;/span&gt;</content>
      <content name="organizationName">National Library of Medicine</content>
      <content name="altTitle">&lt;span class="qt0"&gt;Asthma&lt;/span&gt;</content>
      <content name="altTitle">Bronchial Asthma</content>
      <content name="snippet">What is &lt;span class="qt0"&gt;asthma? Asthma&lt;/span&gt; is a chronic (long-term) lung disease.</content>
      <content name="mesh">&lt;span class="qt0"&gt;Asthma&lt;/span&gt;</content>
      <content name="groupName">Lungs and Breathing</content>
      <content name="groupName">Immune System</content>
    </document>
    <document rank="2" url="https://medlineplus.gov/asthmainchildren.html">
      <content name="title">&lt;span class="qt0"&gt;Asthma&lt;/span&gt; in Children</content>
      <content name="organizationName">National Library of Medicine</content>
      <content name="FullSummary">Asthma is a chronic disease in children.</content>
      <content name="groupName">Children and Teenagers</content>
    </document>
    <document rank="3" url="https://medlineplus.gov/noname.html">
      <content name="organizationName">Nobody</content>
    </document>
  </list>
</nlmSearchResult>
"""


def _provider() -> MedlinePlusProvider:
    """Return a fresh provider instance for each test."""
    return MedlinePlusProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "medlineplus"
    assert p.tags == ["web", "medical", "health", "reference"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "medlineplus" in registry
    assert registry["medlineplus"].tags == ["web", "medical", "health", "reference"]


@pytest.mark.asyncio
async def test_search_builds_structured_results(respx_mock) -> None:
    route = respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, text=_XML),
    )

    result = await _provider().search("asthma", SearchParams(num_results=10))

    assert route.called
    request = route.calls.last.request
    assert request.url.params["db"] == "healthTopics"
    assert request.url.params["term"] == "asthma"
    assert request.url.params["retmax"] == "10"

    assert [r.title for r in result.results] == ["Asthma", "Asthma in Children"]

    first = result.results[0]
    assert first.url == "https://medlineplus.gov/asthma.html"
    assert first.source == "medlineplus.gov"
    assert first.provider == "medlineplus"
    assert first.rank == 1
    assert first.snippet == (
        "National Library of Medicine | What is asthma? Asthma is a chronic "
        "(long-term) lung disease."
    )
    assert first.extra == {
        "organization": "National Library of Medicine",
        "alt_titles": ["Asthma", "Bronchial Asthma"],
        "groups": ["Lungs and Breathing", "Immune System"],
        "mesh": "Asthma",
    }

    second = result.results[1]
    assert second.rank == 2
    assert second.snippet == (
        "National Library of Medicine | Asthma is a chronic disease in children."
    )
    assert second.extra["alt_titles"] == []
    assert second.extra["mesh"] is None
    assert second.extra["groups"] == ["Children and Teenagers"]


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    respx_mock.get(_API_URL).mock(return_value=respx.MockResponse(200, text=_XML))

    result = await _provider().search("asthma", SearchParams(num_results=1))

    assert len(result.results) == 1
    assert result.results[0].rank == 1


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_API_URL).mock(return_value=respx.MockResponse(200))

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_malformed_xml_is_not_an_error(respx_mock) -> None:
    respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, text="<broken"),
    )

    result = await _provider().search("asthma", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "",
        "<nlmSearchResult></nlmSearchResult>",
        "<something><else/></something>",
    ],
)
async def test_search_handles_unexpected_payload_shapes(respx_mock, text) -> None:
    respx_mock.get(_API_URL).mock(return_value=respx.MockResponse(200, text=text))

    result = await _provider().search("asthma", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_search_propagates_http_errors(respx_mock) -> None:
    respx_mock.get(_API_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("asthma", SearchParams(num_results=5))


def test_build_result_returns_none_without_title() -> None:
    p = _provider()
    doc = ET.fromstring(
        '<document rank="1" url="https://medlineplus.gov/x.html">'
        '<content name="organizationName">NLM</content>'
        "</document>",
    )
    assert p._build_result(doc, 1) is None


def test_build_result_returns_none_without_url() -> None:
    p = _provider()
    doc = ET.fromstring(
        '<document rank="1"><content name="title">X</content></document>'
    )
    assert p._build_result(doc, 1) is None


def test_build_result_falls_back_to_alt_title() -> None:
    p = _provider()
    doc = ET.fromstring(
        '<document rank="1" url="https://medlineplus.gov/x.html">'
        '<content name="altTitle">Fallback Name</content>'
        "</document>",
    )
    built = p._build_result(doc, 1)
    assert built is not None
    assert built.title == "Fallback Name"
    assert built.snippet == ""
    assert built.extra["organization"] is None
