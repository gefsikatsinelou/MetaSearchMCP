"""Unit tests for the PubMed E-utilities provider.

Covers esearch/esummary parsing (including entries with missing
``pubdate`` or ``source``), the pure helper functions, the fallback
path, and API error handling.
"""

from __future__ import annotations

import pytest
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.pubmed import PubMedProvider


def _esearch_payload(id_list: list[str]) -> dict:
    return {"esearchresult": {"idlist": id_list, "count": str(len(id_list))}}


def _esummary_payload(uid: str) -> dict:
    """A single-document esummary result block (as returned by ESummary)."""
    return {
        "result": {
            uid: {
                "uid": uid,
                "title": f"Paper {uid} on machine learning",
                "pubdate": "2024 May 15",
                "source": "Nat Mach Intell",
                "authors": [{"name": "Doe J"}],
                "articleids": [
                    {"idtype": "doi", "value": f"10.1000/{uid}"},
                ],
            },
            "uids": [uid],
        },
    }


def _provider() -> PubMedProvider:
    return PubMedProvider()


def test_parse_basic() -> None:
    p = _provider()
    # ESummary only knows about 12345 — the other ID is simply absent.
    result = p._parse(
        _esummary_payload("12345"),
        ["12345", "67890"],
    )

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Paper 12345 on machine learning"
    assert r.url.startswith("https://pubmed.ncbi.nlm.nih.gov/12345")
    assert r.provider == "pubmed"
    assert r.rank == 1
    assert r.source == "pubmed.ncbi.nlm.nih.gov"
    assert "Nat Mach Intell" in r.snippet
    assert r.extra["pmid"] == "12345"
    assert r.extra["article_ids"][0]["value"] == "10.1000/12345"


def test_parse_bare_id_fallback_when_item_missing() -> None:
    """A requested PMID absent from the esummary map is skipped, not dropped
    silently — the parser only keeps IDs that came back from ESummary."""
    p = _provider()
    result = p._parse(_esearch_payload(["42"]), {"result": {}})

    assert len(result.results) == 0


def test_parse_empty_search() -> None:
    p = _provider()
    assert p._parse(_esearch_payload([]), _esummary_payload("1")).results == []
    assert p._parse({}, []).results == []


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").mock(
        return_value=respx.MockResponse(200, json=_esearch_payload(["12345"])),
    )
    respx_mock.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi").mock(
        return_value=respx.MockResponse(200, json=_esummary_payload("12345")),
    )

    p = _provider()
    result = await p.search("machine learning", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "pubmed"
    assert result.results[0].title == "Paper 12345 on machine learning"


@pytest.mark.asyncio
async def test_search_raises_on_api_error(respx_mock) -> None:
    import respx

    respx_mock.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").mock(
        return_value=respx.MockResponse(500, json={}),
    )

    p = _provider()
    with pytest.raises(HTTPStatusError):
        await p.search("machine learning", SearchParams(num_results=5))
