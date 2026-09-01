"""Unit tests for the RxNorm clinical drug terminology provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.rxnorm import RxNormProvider

_SAMPLE_CONCEPTS = [
    {
        "rxcui": "1100070",
        "name": "famotidine 26.6 MG / ibuprofen 800 MG Oral Tablet [Duexis]",
        "synonym": "Duexis (famotidine 26.6 MG / ibuprofen 800 MG) Oral Tablet",
        "tty": "SBD",
        "language": "ENG",
        "suppress": "N",
        "umlscui": "C4057751",
    },
    {
        "rxcui": "1049589",
        "name": "ibuprofen 400 MG / oxycodone hydrochloride 5 MG Oral Tablet",
        "synonym": "",
        "tty": "SCD",
        "language": "ENG",
        "suppress": "N",
        "umlscui": "C2363142",
    },
    {
        # Duplicate RxCUI (same concept under another term-type group) -> deduped.
        "rxcui": "1100070",
        "name": "famotidine 26.6 MG / ibuprofen 800 MG Oral Tablet [Duexis]",
        "synonym": "Duexis",
        "tty": "SCD",
        "language": "ENG",
        "suppress": "N",
    },
    {
        # Missing RxCUI -> skipped.
        "name": "aspirin 81 MG Oral Tablet",
        "tty": "SCD",
        "language": "ENG",
    },
]

_SAMPLE_RESPONSE: dict[str, object] = {
    "drugGroup": {
        "name": None,
        "conceptGroup": [
            {"tty": "SBD", "conceptProperties": [_SAMPLE_CONCEPTS[0]]},
            {
                "tty": "SCD",
                "conceptProperties": [_SAMPLE_CONCEPTS[1], _SAMPLE_CONCEPTS[2]],
            },
            {"tty": "SCD", "conceptProperties": [_SAMPLE_CONCEPTS[3]]},
        ],
    },
}

_EMPTY_RESPONSE: dict[str, object] = {"drugGroup": {"conceptGroup": []}}


def _provider() -> RxNormProvider:
    return RxNormProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "rxnorm"
    assert p.tags == ["drugs", "pharma", "medical", "bio"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "famotidine 26.6 MG / ibuprofen 800 MG Oral Tablet [Duexis]"
    assert r.url == "https://rxnav.nlm.nih.gov/id/rxnorm/1100070"
    assert "Duexis (famotidine 26.6 MG / ibuprofen 800 MG) Oral Tablet" in r.snippet
    assert "SBD" in r.snippet
    assert "RxCUI 1100070" in r.snippet
    assert r.provider == "rxnorm"
    assert r.source == "rxnav.nlm.nih.gov"
    assert r.rank == 1
    assert r.extra["rxcui"] == 1100070
    assert r.extra["term_type"] == "SBD"
    assert r.extra["umls_cui"] == "C4057751"


def test_parse_dedupes_by_rxcui() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    rxcuis = [r.extra["rxcui"] for r in result.results]
    assert len(rxcuis) == len(set(rxcuis))
    assert 1100070 in rxcuis
    assert 1049589 in rxcuis


def test_parse_prefers_branded_term_type() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    # SBD (1100070) sorts before SCD (1049589).
    assert result.results[0].extra["term_type"] == "SBD"
    assert result.results[1].extra["term_type"] == "SCD"


def test_parse_skips_concepts_without_rxcui_or_name() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert all(r.extra["rxcui"] for r in result.results)
    assert len(result.results) == 2


def test_parse_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1
    assert result.results[0].extra["rxcui"] == 1100070


def test_parse_empty_and_malformed() -> None:
    assert _provider()._parse(_EMPTY_RESPONSE).results == []
    assert _provider()._parse({}).results == []
    assert _provider()._parse({"drugGroup": None}).results == []
    assert _provider()._parse({"drugGroup": {"conceptGroup": None}}).results == []
    assert _provider()._parse({"drugGroup": {"conceptGroup": "junk"}}).results == []
    assert _provider()._parse(None).results == []
    assert _provider()._parse([]).results == []


def test_concept_key_fallback_rank() -> None:
    # Unknown term types sort after all preferred ones.
    unknown = RxNormProvider._concept_key({"tty": "ZZZ", "rxcui": "1"})
    preferred = RxNormProvider._concept_key({"tty": "SBD", "rxcui": "2"})
    assert unknown > preferred


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get("https://rxnav.nlm.nih.gov/REST/drugs.json").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("ibuprofen", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "rxnorm"
    request = respx_mock.calls.last.request
    assert request.url.params["name"] == "ibuprofen"


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://rxnav.nlm.nih.gov/REST/drugs.json").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("zzzz", SearchParams(num_results=5))
    assert result.results == []
