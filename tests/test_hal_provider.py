"""Unit tests for the HAL Open Science scholarly search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.hal import HalProvider, _clean, _string_list

_SAMPLE_RESPONSE: dict[str, object] = {
    "response": {
        "numFound": 1219,
        "start": 0,
        "maxScore": 9.88,
        "docs": [
            {
                "title_s": ["The CRISPR-Cas9 System: A New Dawn in Gene Editing"],
                "abstract_s": [
                    (
                        "The CRISPR-Cas9 system is a genome editing system. "
                        "It is efficient and easy to design."
                    ),
                ],
                "authFullName_s": [
                    "Nurul Husna Shafie",
                    "Mohamed Saleem",
                    "Emmanuel Jairaj Moses",
                    "Narazah Mohd Yusoff",
                ],
                "journalTitle_s": "Journal of Bioanalysis & Biomedicine",
                "language_s": ["en"],
                "halId_s": "hal-04020890",
                "uri_s": "https://hal.science/hal-04020890v1",
                "docType_s": "ART",
                "doiId_s": "10.4172/1948-593x.1000109",
                "producedDate_s": "2014-11-07",
                "producedDateY_i": 2014,
                "keyword_s": ["CRISPR", "Gene editing"],
                "citationRef_s": (
                    "<i>Journal of Bioanalysis</i>, 2014 "
                    '<a href="https://dx.doi.org/10">&#x27E8;DOI&#x27E9;</a>'
                ),
            },
            {
                # Multiple title variants; partial date; 4 authors; no abstract.
                "title_s": ["Titre francais", "English title"],
                "authFullName_s": ["Alice A", "Bob B", "Carol C", "Dave D"],
                "uri_s": "https://hal.science/hal-01479136v1",
                "docType_s": "UNDEFINED",
                "producedDate_s": "2017-12",
                "producedDateY_i": 2017,
            },
            # No title -> skipped entirely.
            {"title_s": [], "uri_s": "https://hal.science/hal-empty"},
            # Non-http URI -> skipped entirely.
            {"title_s": ["No uri"], "uri_s": "ftp://hal.science/nope"},
            "junk",
        ],
    },
}

_EMPTY_RESPONSE: dict[str, object] = {
    "response": {"numFound": 0, "start": 0, "docs": []},
}


def _provider() -> HalProvider:
    return HalProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "hal"
    assert p.tags == ["academic", "web"]
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "hal" in registry
    assert registry["hal"].tags == ["academic", "web"]


def test_parse_basic_fields() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "The CRISPR-Cas9 System: A New Dawn in Gene Editing"
    assert r.url == "https://hal.science/hal-04020890v1"
    assert r.provider == "hal"
    assert r.source == "hal.science"
    assert r.rank == 1
    assert r.published_date == "2014-11-07"
    # Abstract is whitespace-collapsed into a single line.
    assert "genome editing system. It is efficient" in r.snippet
    assert "Journal of Bioanalysis & Biomedicine" in r.snippet
    assert "Nurul Husna Shafie, Mohamed Saleem, Emmanuel Jairaj Moses, et al." in (
        r.snippet
    )
    assert "Type: journal article" in r.snippet
    assert "Keywords: CRISPR, Gene editing" in r.snippet
    assert r.extra["doi"] == "10.4172/1948-593x.1000109"
    assert r.extra["hal_id"] == "hal-04020890"
    assert r.extra["doc_type"] == "ART"
    assert r.extra["doc_type_label"] == "journal article"
    assert r.extra["language"] == "en"
    assert r.extra["year"] == 2014
    assert r.extra["produced_date"] == "2014-11-07"
    assert r.extra["total_results"] == 1219
    assert len(r.extra["authors"]) == 4


def test_parse_second_document_edges() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    second = result.results[1]
    # First title variant is used verbatim.
    assert second.title == "Titre francais"
    assert second.rank == 2
    # Partial date (YYYY-MM) is not emitted as a published_date.
    assert second.published_date is None
    assert second.extra["produced_date"] == "2017-12"
    # UNDEFINED maps to the "preprint" label.
    assert second.extra["doc_type_label"] == "preprint"
    assert "Alice A, Bob B, Carol C, et al." in second.snippet
    assert "Type: preprint" in second.snippet
    # No abstract, journal or keywords -> they are simply absent.
    assert "|  |" not in second.snippet


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse({}).results == []
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({"response": {"docs": "nope"}}).results == []
    assert p._parse({"response": "nope"}).results == []
    assert p._parse({"response": {"docs": [42, None]}}).results == []
    assert p._parse("junk").results == []


def test_parse_respects_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1
    assert result.results[0].rank == 1


def test_string_list_helper() -> None:
    assert _string_list("a") == ["a"]
    assert _string_list(["a", 2, "b"]) == ["a", "b"]
    assert _string_list(None) == []


def test_clean_strips_html_and_whitespace() -> None:
    cleaned = _clean("<i>Journal</i>,\n 2014 <a href='#'>x</a>")
    assert "<i>" not in cleaned
    assert "<a" not in cleaned
    assert "Journal" in cleaned
    assert "\n" not in cleaned


def test_published_date_helper() -> None:
    assert HalProvider._published_date({"producedDate_s": "2014-11-07"}) == "2014-11-07"
    assert HalProvider._published_date({"producedDate_s": "2017-12"}) is None
    assert HalProvider._published_date({}) is None


def test_doc_type_label_fallbacks() -> None:
    assert HalProvider._doc_type_label("ART") == "journal article"
    assert HalProvider._doc_type_label("THESE") == "thesis"
    assert HalProvider._doc_type_label("WHAT") == "what"
    assert HalProvider._doc_type_label("") == ""


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.archives-ouvertes.fr/search/").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    result = await _provider().search("gene editing", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "hal"
    assert len(respx_mock.calls) == 1
    request = respx_mock.calls[0].request
    assert request.url.params["q"] == "gene editing"
    assert request.url.params["wt"] == "json"
    assert request.url.params["rows"] == "5"
    assert "title_s" in request.url.params["fl"]


@pytest.mark.asyncio
async def test_search_no_match(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.archives-ouvertes.fr/search/").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    result = await _provider().search("zzzz", SearchParams(num_results=5))
    assert result.results == []
