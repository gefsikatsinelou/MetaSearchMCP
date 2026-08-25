"""Unit tests for the DBLP computer-science bibliography search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.dblp import DBLPProvider

_RESPONSE = {
    "result": {
        "status": {"@code": "200", "text": "OK"},
        "hits": {
            "@total": "2",
            "@computed": "2",
            "@sent": "2",
            "hit": [
                {
                    "@score": "6",
                    "@id": "758249",
                    "info": {
                        "authors": {
                            "author": [
                                {"@pid": "299/6533", "text": "Yubao Tang"},
                                {"@pid": "02/146", "text": "Jiafeng Guo"},
                            ],
                        },
                        "title": "Boosting Retrieval-Augmented Generation.",
                        "venue": "SIGIR",
                        "pages": "2441-2451",
                        "year": "2025",
                        "type": "Conference and Workshop Papers",
                        "doi": "10.1145/3726302.3729907",
                        "url": "https://dblp.org/rec/conf/sigir/Tang0GRFC25",
                        "ee": "https://doi.org/10.1145/3726302.3729907",
                        "key": "conf/sigir/Tang0GRFC25",
                    },
                },
                {
                    "@score": "5",
                    "@id": "758250",
                    "info": {
                        "authors": {
                            "author": {"@pid": "44/912-1", "text": "Xueqi Cheng"}
                        },
                        "title": "Single-author paper.",
                        "venue": "Expert Syst. Appl.",
                        "year": "2027",
                        "type": "Journal Articles",
                        "doi": "10.1016/J.ESWA.2026.133921",
                        "url": "https://dblp.org/rec/journals/eswa/LiuHYZZWG27",
                        "ee": "https://doi.org/10.1016/j.eswa.2026.133921",
                        "key": "journals/eswa/LiuHYZZWG27",
                    },
                },
            ],
        },
    },
}


def _provider() -> DBLPProvider:
    return DBLPProvider()


def test_parse_basic() -> None:
    result = _provider()._parse(_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Boosting Retrieval-Augmented Generation."
    assert r.url == "https://dblp.org/rec/conf/sigir/Tang0GRFC25"
    assert r.provider == "dblp"
    assert r.source == "dblp.org"
    assert r.rank == 1
    assert r.published_date == "2025"
    assert "Venue: SIGIR" in r.snippet
    assert "Year: 2025" in r.snippet
    assert "Conference and Workshop Papers" in r.snippet
    assert r.extra["authors"] == ["Yubao Tang", "Jiafeng Guo"]
    assert r.extra["venue"] == "SIGIR"
    assert r.extra["year"] == "2025"
    assert r.extra["type"] == "Conference and Workshop Papers"
    assert r.extra["doi"] == "10.1145/3726302.3729907"
    assert r.extra["ee"] == "https://doi.org/10.1145/3726302.3729907"


def test_parse_single_author_dict() -> None:
    # DBLP returns a bare dict (not a list) for a single author.
    result = _provider()._parse(_RESPONSE)
    assert result.results[1].extra["authors"] == ["Xueqi Cheng"]


def test_parse_skips_entries_without_title_or_url() -> None:
    data = {
        "result": {
            "hits": {
                "hit": [
                    {"info": {"title": "  ", "url": ""}},
                    {"info": {"url": "https://dblp.org/rec/x", "title": ""}},
                    {"info": {"title": "T", "url": ""}},
                    "not-a-dict",
                    None,
                ],
            },
        },
    }
    assert _provider()._parse(data).results == []


def test_parse_empty_and_malformed() -> None:
    assert _provider()._parse({}).results == []
    assert _provider()._parse({"result": {"hits": {"hit": "not-a-list"}}}).results == []


def test_parse_limit() -> None:
    result = _provider()._parse(_RESPONSE, max_results=1)
    assert len(result.results) == 1
    assert result.results[0].extra["year"] == "2025"


def test_parse_url_fallback_to_rec_key() -> None:
    hit = {
        "info": {
            "title": "Paper without url",
            "key": "conf/iclr/Example23",
            "year": "2023",
        },
    }
    result = _provider()._parse({"result": {"hits": {"hit": [hit]}}})
    assert result.results[0].url == "https://dblp.org/rec/conf/iclr/Example23"


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_endpoint(respx_mock) -> None:
    import respx

    respx_mock.get(
        "https://dblp.org/search/publ/api",
        params={"q": "retrieval augmented generation", "format": "json", "h": 5},
    ).mock(
        return_value=respx.MockResponse(200, json=_RESPONSE),
    )

    p = _provider()
    result = await p.search(
        "retrieval augmented generation",
        SearchParams(num_results=5),
    )

    assert len(result.results) == 2
    assert result.results[0].provider == "dblp"
    assert result.results[0].url.startswith("https://dblp.org/rec/")
