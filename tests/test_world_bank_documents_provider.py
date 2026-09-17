"""Unit tests for the World Bank Documents & Reports search provider."""

from __future__ import annotations

import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH
from metasearchmcp.providers.world_bank_documents import (
    WorldBankDocumentsProvider,
    _nested_text,
)

_SEARCH_URL = "https://search.worldbank.org/api/v2/wds"

_PUBLICATION_URL = (
    "http://documents.worldbank.org/curated/en/933151468740676854/"
    "Malaria-new-patterns-and-perspectives"
)
_PDF_URL = "http://documents.worldbank.org/curated/en/0001/pdf/P0964820.pdf"
_TEXT_URL = "http://documents.worldbank.org/curated/en/0001/text/P0964820.txt"

_SEARCH_RESPONSE: dict[str, object] = {
    "rows": 3,
    "os": 0,
    "page": 1,
    "total": 536,
    "documents": {
        "D440424": {
            "id": "440424",
            "docna": {"0": {"docna": "Malaria : new patterns and perspectives"}},
            "docty": "Publication",
            "lang": "English",
            "repnb": "WTP183",
            "docdt": "1992-09-30T00:00:00Z",
            "abstracts": {
                "cdata!": "Malaria is a collective name for\n"
                "            different diseases."
            },
            "display_title": "Malaria : new patterns and perspectives",
            "guid": "933151468740676854",
            "url": _PUBLICATION_URL,
        },
        "D6783044": {
            "id": "6783044",
            "docna": {"0": {"docna": "Benin - Malaria Control Support Project"}},
            "display_title": "Benin - Malaria Control Support Project",
            "docty": "Project Appraisal Document",
            "projn": "BJ-Benin: Malaria Control Booster Program -- P096482",
            "count": "Benin",
            "repnb": "35555",
            "lang": "English",
            "docdt": "2006-05-03T00:00:00Z",
            "guid": "000090341_20060511094932",
            "pdfurl": _PDF_URL,
            "txturl": _TEXT_URL,
        },
        "facets": {},
        "D999": {
            "id": "999",
            "docna": {"0": {"docna": "   "}},
            "docty": "Loan Agreement",
        },
    },
}

_EMPTY_RESPONSE: dict[str, object] = {
    "rows": 3,
    "os": 0,
    "page": 1,
    "total": 0,
    "documents": {"facets": {}},
}


def _provider() -> WorldBankDocumentsProvider:
    return WorldBankDocumentsProvider()


def test_name_tags_and_description() -> None:
    p = _provider()
    assert p.name == "worldbank_documents"
    assert p.tags == ["academic", "data", "gov", "reference"]
    assert "No API key required" in p.description


def test_parse_builds_results_in_api_order() -> None:
    result = _provider()._parse(_SEARCH_RESPONSE)

    assert [r.title for r in result.results] == [
        "Malaria : new patterns and perspectives",
        "Benin - Malaria Control Support Project",
    ]


def test_parse_uses_the_abstract_as_snippet() -> None:
    first = _provider()._parse(_SEARCH_RESPONSE).results[0]

    assert first.snippet == "Malaria is a collective name for different diseases."
    assert first.url == _PUBLICATION_URL
    assert first.source == "documents.worldbank.org"
    assert first.provider == "worldbank_documents"
    assert first.rank == 1
    assert first.published_date == "1992-09-30"
    assert first.extra == {
        "id": "440424",
        "guid": "933151468740676854",
        "document_type": "Publication",
        "language": "English",
        "report_number": "WTP183",
        "project": None,
        "country": None,
        "pdf_url": None,
        "text_url": None,
        "total_results": 536,
        "url": _PUBLICATION_URL,
    }


def test_parse_falls_back_to_metadata_snippet_and_guid_url() -> None:
    second = _provider()._parse(_SEARCH_RESPONSE).results[1]

    assert second.rank == 2
    assert second.published_date == "2006-05-03"
    assert second.url == (
        "https://documents.worldbank.org/en/publication/documents-reports/"
        "documentdetail/000090341_20060511094932"
    )
    assert second.snippet == (
        "Type: Project Appraisal Document | "
        "Project: BJ-Benin: Malaria Control Booster Program -- P096482 | "
        "Country: Benin | Report: 35555 | Language: English"
    )
    assert second.extra["country"] == "Benin"
    assert second.extra["pdf_url"] == _PDF_URL
    assert second.extra["text_url"] == _TEXT_URL


def test_parse_skips_the_facets_entry_and_untitled_documents() -> None:
    result = _provider()._parse(_SEARCH_RESPONSE)

    assert len(result.results) == 2
    assert all(r.title for r in result.results)


def test_parse_truncates_long_abstracts() -> None:
    record = {
        "display_title": "Long report",
        "abstracts": {"cdata!": "word " * 200},
    }

    only = _provider()._parse({"documents": {"D1": record}}).results[0]

    assert len(only.snippet) == MAX_SNIPPET_LENGTH


def test_url_prefers_the_api_link_then_the_friendly_title() -> None:
    friendly = {"display_title": "Doc", "url_friendly_title": _PUBLICATION_URL}
    assert _provider()._url(friendly) == _PUBLICATION_URL

    by_id = {"display_title": "Doc", "id": "12345"}
    assert _provider()._url(by_id) == (
        "https://documents.worldbank.org/en/publication/documents-reports/"
        "documentdetail/12345"
    )

    assert _provider()._url({"display_title": "Doc"}) == (
        "https://documents.worldbank.org/"
    )


def test_parse_empty_and_malformed_payloads() -> None:
    p = _provider()
    assert p._parse(None).results == []
    assert p._parse([]).results == []
    assert p._parse({}).results == []
    assert p._parse("junk").results == []
    assert p._parse({"documents": "junk"}).results == []
    assert p._parse({"documents": {"D1": "junk", "D2": 42}}).results == []
    assert p._parse({"documents": {"facets": {"countries": []}}}).results == []


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse(_SEARCH_RESPONSE, limit=1).results) == 1
    assert len(p._parse(_SEARCH_RESPONSE, 2).results) == 2


def test_nested_text_walks_the_api_wrappers() -> None:
    assert _nested_text({"0": {"docna": "  Hello  world "}}) == "Hello world"
    assert _nested_text({"cdata!": "Abstract text"}) == "Abstract text"
    assert _nested_text(["", {"x": "deep"}]) == "deep"
    assert _nested_text(None) == ""
    assert _nested_text(42) == ""
    assert _nested_text({}) == ""


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "worldbank_documents" in registry
    assert registry["worldbank_documents"].tags == [
        "academic",
        "data",
        "gov",
        "reference",
    ]


@pytest.mark.asyncio
async def test_search_queries_the_json_endpoint(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json=_SEARCH_RESPONSE)
    )

    p = _provider()
    result = await p.search("malaria vaccine", SearchParams(num_results=5))

    assert [r.title for r in result.results] == [
        "Malaria : new patterns and perspectives",
        "Benin - Malaria Control Support Project",
    ]
    call = respx_mock.calls[0]
    assert call.request.url.params["qterm"] == "malaria vaccine"
    assert call.request.url.params["rows"] == "5"
    assert call.request.url.params["format"] == "json"
    assert "abstracts" in call.request.url.params["fl"]


@pytest.mark.asyncio
async def test_search_respects_provider_max_results(respx_mock) -> None:
    documents = {
        f"D{n}": {"display_title": f"Document {n}", "id": str(n)} for n in range(40)
    }
    respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, json={"documents": documents})
    )

    p = _provider()
    result = await p.search("development", SearchParams(num_results=50))

    assert len(result.results) == p._max_results
    assert result.results[-1].rank == p._max_results


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
    result = await p.search("zzzzqqqxxyy123", SearchParams(num_results=5))

    assert result.results == []
