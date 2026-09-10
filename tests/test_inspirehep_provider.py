"""Unit tests for the INSPIRE-HEP high-energy physics literature provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.inspirehep import InspireHEPProvider

_SAMPLE_RESPONSE: dict[str, object] = {
    "hits": {
        "total": 3,
        "hits": [
            {
                "id": 3201956,
                "metadata": {
                    "titles": [
                        {
                            "source": "arXiv",
                            "title": "Higgsino Dark Matter at Colliders",
                        }
                    ],
                    "authors": [
                        {"full_name": "Chatterjee, Arindam"},
                        {"full_name": "Das, Debottam"},
                        {"full_name": "Pasha, Syed Adil"},
                    ],
                    "abstracts": [
                        {
                            "value": (
                                "The direct detection of Higgsino-like dark matter ..."
                            )
                        }
                    ],
                    "arxiv_eprints": [
                        {"categories": ["hep-ph"], "value": "2609.09830"}
                    ],
                    "publication_info": [
                        {
                            "journal_title": "JHEP",
                            "journal_volume": "05",
                            "page_start": "123",
                            "year": "2026",
                        }
                    ],
                    "dois": [{"value": "10.1007/JHEP05(2026)123"}],
                    "citation_count": 7,
                    "earliest_date": "2026-09-09T00:00:00+00:00",
                    "document_type": ["article"],
                },
            },
            {
                # Freetext journal reference, no arXiv id, no abstract.
                "id": 3201628,
                "metadata": {
                    "titles": [{"title": "Bogomol'nyi equations for Kruglov strings"}],
                    "authors": [{"full_name": "Praseyto, I."}],
                    "publication_info": [
                        {"pubinfo_freetext": "Phys. Rev. D 110 (2026) 045678"}
                    ],
                    "citation_count": 0,
                    "earliest_date": "2026-09-08",
                    "document_type": ["article", "preprint"],
                },
            },
            {
                # No title -> skipped.
                "id": 9999999,
                "metadata": {"authors": [{"full_name": "Nobody"}]},
            },
            {
                # No record id -> skipped.
                "metadata": {"titles": [{"title": "Orphan record"}]},
            },
            "junk",
            None,
        ],
    },
}

_EMPTY_RESPONSE: dict[str, object] = {"hits": {"total": 0, "hits": []}}


def _provider() -> InspireHEPProvider:
    return InspireHEPProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "inspirehep"
    assert p.tags == ["academic", "web", "science", "physics"]
    assert p.description


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Higgsino Dark Matter at Colliders"
    assert r.url == "https://inspirehep.net/literature/3201956"
    assert r.source == "inspirehep.net"
    assert r.provider == "inspirehep"
    assert r.rank == 1
    assert r.published_date == "2026-09-09"
    assert "Higgsino-like dark matter" in r.snippet
    assert "Authors: Chatterjee, Arindam, Das, Debottam, Pasha, Syed Adil" in r.snippet
    assert "Journal: JHEP 05 (2026) 123" in r.snippet
    assert "arXiv: 2609.09830" in r.snippet
    assert "Cited by: 7" in r.snippet
    assert r.extra["inspire_id"] == "3201956"
    assert r.extra["arxiv_id"] == "2609.09830"
    assert r.extra["arxiv_categories"] == ["hep-ph"]
    assert r.extra["doi"] == "10.1007/JHEP05(2026)123"
    assert r.extra["journal_ref"] == "JHEP 05 (2026) 123"
    assert r.extra["citation_count"] == 7
    assert r.extra["document_type"] == ["article"]


def test_parse_freetext_journal_and_no_abstract() -> None:
    r = _provider()._parse(_SAMPLE_RESPONSE).results[1]
    assert r.published_date == "2026-09-08"
    assert r.extra["journal_ref"] == "Phys. Rev. D 110 (2026) 045678"
    assert r.extra["arxiv_id"] == ""
    assert r.extra["doi"] == ""
    assert r.extra["citation_count"] == 0
    assert r.extra["document_type"] == ["article", "preprint"]
    # No citations -> no "Cited by" tail.
    assert "Cited by" not in r.snippet


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
    assert p._parse({"hits": "nope"}).results == []  # type: ignore[arg-type]


def test_parse_snippet_capped_at_shared_limit() -> None:
    from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH

    long_text = "x" * (MAX_SNIPPET_LENGTH + 200)
    result = _provider()._parse(
        {
            "hits": {
                "hits": [
                    {
                        "id": 1,
                        "metadata": {
                            "titles": [{"title": "Long"}],
                            "abstracts": [{"value": long_text}],
                        },
                    }
                ]
            }
        }
    )
    assert len(result.results[0].snippet) == MAX_SNIPPET_LENGTH


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_query(respx_mock) -> None:
    import respx

    respx_mock.get("https://inspirehep.net/api/literature").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("higgs boson", SearchParams(num_results=5))

    assert len(result.results) == 2
    request = respx_mock.calls.last.request
    assert request.url.params["q"] == "higgs boson"
    assert request.url.params["size"] == "5"
    assert request.url.params["sort"] == "mostrecent"
    assert "titles" in request.url.params["fields"]


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://inspirehep.net/api/literature").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("no-such-paper-xyz", SearchParams(num_results=5))
    assert result.results == []
