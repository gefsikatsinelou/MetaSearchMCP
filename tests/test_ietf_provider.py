"""Unit tests for the IETF Datatracker document provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.ietf import IetfProvider

_API_URL = "https://datatracker.ietf.org/api/v1/doc/document/"

_RFC_ITEM = {
    "name": "rfc9221",
    "title": "An Unreliable Datagram Extension to QUIC",
    "abstract": (
        "This document defines an extension to the QUIC transport protocol "
        "to add support for sending unreliable datagrams."
    ),
    "type": "/api/v1/name/doctypename/rfc/",
    "rfc": "9221",
    "rfc_number": 9221,
    "std_level": "/api/v1/name/stdlevelname/ps/",
    "stream": "/api/v1/name/streamname/ietf/",
    "pages": 9,
    "keywords": "[]",
    "expires": None,
    "time": "2026-05-20T15:17:16Z",
}

# Only returned by the abstract call in the sample payloads below.
_DRAFT_ITEM = {
    "name": "draft-ietf-quic-datagram",
    "title": "QUIC Datagrams",
    "abstract": "Unreliable datagram support for QUIC.",
    "type": "/api/v1/name/doctypename/draft/",
    "rfc": "",
    "rfc_number": None,
    "std_level": None,
    "stream": "/api/v1/name/streamname/ietf/",
    "pages": 21,
    "keywords": "['quic', 'datagram']",
    "expires": "2021-05-01T00:00:00Z",
    "time": "2020-11-01T00:00:00Z",
}

# Also matched by the abstract call, but its title only covers one token.
_SECOND_RFC_ITEM = {
    "name": "rfc9000",
    "title": "QUIC: A UDP-Based Multiplexed and Secure Transport",
    "abstract": "This document defines the core of the QUIC transport protocol.",
    "type": "/api/v1/name/doctypename/rfc/",
    "rfc": "9000",
    "rfc_number": 9000,
    "std_level": "/api/v1/name/stdlevelname/std/",
    "stream": "/api/v1/name/streamname/ietf/",
    "pages": 151,
    "keywords": "[]",
    "expires": None,
    "time": "2021-05-27T00:00:00Z",
}

_TITLE_PAYLOAD: dict[str, object] = {
    "meta": {"limit": 10, "offset": 0, "total_count": 2},
    "objects": [
        _RFC_ITEM,
        # Meeting slides are stored under the same endpoint but are not
        # standards documents.
        {
            "name": "slides-122-quic-1",
            "title": "QUIC Working Group Slides",
            "type": "/api/v1/name/doctypename/slides/",
        },
        {"name": "", "title": "Nameless", "type": "/api/v1/name/doctypename/rfc/"},
        "not-a-mapping",
    ],
}

_ABSTRACT_PAYLOAD: dict[str, object] = {
    "meta": {"limit": 10, "offset": 0, "total_count": 3},
    "objects": [
        _DRAFT_ITEM,
        _RFC_ITEM,  # duplicate of a title hit -> dropped
        _SECOND_RFC_ITEM,
    ],
}


def _provider() -> IetfProvider:
    """Return a fresh provider instance for each test."""
    return IetfProvider()


def _mock_search(
    respx_mock,
    title_payload: object = _TITLE_PAYLOAD,
    abstract_payload: object = _ABSTRACT_PAYLOAD,
):
    """Route Datatracker calls to a payload based on the filter used."""

    def _handler(request):
        if "title__icontains" in request.url.params:
            return respx.MockResponse(200, json=title_payload)
        return respx.MockResponse(200, json=abstract_payload)

    return respx_mock.get(_API_URL).mock(side_effect=_handler)


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "ietf"
    assert p.tags == ["web", "developer", "standards", "reference"]
    assert "keyless" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "ietf" in registry
    assert registry["ietf"].tags == ["web", "developer", "standards", "reference"]


def test_code_extracts_uri_slugs() -> None:
    assert IetfProvider._code("/api/v1/name/stdlevelname/ps/") == "ps"
    assert IetfProvider._code("/api/v1/name/streamname/ietf") == "ietf"
    assert IetfProvider._code(None) == ""
    assert IetfProvider._code(42) == ""
    assert IetfProvider._code("") == ""


def test_keywords_parses_stringified_list() -> None:
    assert IetfProvider._keywords("['quic', 'datagram']") == ["quic", "datagram"]
    assert IetfProvider._keywords("[]") == []
    assert IetfProvider._keywords(None) == []
    assert IetfProvider._keywords(["quic"]) == []
    assert IetfProvider._keywords("['']") == []


def test_tokens_and_title_score() -> None:
    tokens = IetfProvider._tokens("QUIC Datagram!")
    assert tokens == ["quic", "datagram"]
    scored = IetfProvider._title_score(
        "An Unreliable Datagram Extension to QUIC", tokens
    )
    assert scored == 2
    assert IetfProvider._title_score("HTTP Semantics", tokens) == 0
    assert IetfProvider._title_score("QUIC", []) == 0


def test_build_result_skips_non_standards_documents() -> None:
    slides = {"name": "slides-122-quic-1", "title": "Slides", "type": ".../slides/"}
    nameless = {"name": "", "title": "Nameless", "type": ".../rfc/"}
    assert _provider()._build_result(slides) is None
    assert _provider()._build_result(nameless) is None


@pytest.mark.asyncio
async def test_search_ranks_title_matches_first_and_dedupes(respx_mock) -> None:
    _mock_search(respx_mock)

    result = await _provider().search("quic datagram", SearchParams(num_results=10))

    assert [r.title for r in result.results] == [
        "An Unreliable Datagram Extension to QUIC",
        "QUIC Datagrams",
        "QUIC: A UDP-Based Multiplexed and Secure Transport",
    ]
    assert [r.rank for r in result.results] == [1, 2, 3]


@pytest.mark.asyncio
async def test_search_builds_rfc_result(respx_mock) -> None:
    _mock_search(respx_mock)

    result = await _provider().search("quic datagram", SearchParams(num_results=10))
    rfc = result.results[0]

    assert rfc.url == "https://datatracker.ietf.org/doc/rfc9221/"
    assert rfc.source == "datatracker.ietf.org"
    assert rfc.provider == "ietf"
    assert rfc.published_date is None
    assert rfc.snippet.startswith(
        "RFC 9221 | Proposed Standard | IETF | 9 pages | This document defines",
    )
    assert rfc.extra == {
        "doc_name": "rfc9221",
        "kind": "rfc",
        "rfc_number": 9221,
        "std_level": "ps",
        "stream": "ietf",
        "pages": 9,
        "keywords": [],
        "expires": None,
        "updated": "2026-05-20",
    }


@pytest.mark.asyncio
async def test_search_builds_draft_result(respx_mock) -> None:
    _mock_search(respx_mock)

    result = await _provider().search("quic datagram", SearchParams(num_results=10))
    draft = result.results[1]

    assert draft.url == "https://datatracker.ietf.org/doc/draft-ietf-quic-datagram/"
    assert draft.snippet.startswith(
        "Internet-Draft draft-ietf-quic-datagram | IETF | 21 pages | "
        "Keywords: quic, datagram",
    )
    assert draft.extra["kind"] == "draft"
    assert draft.extra["rfc_number"] is None
    assert draft.extra["std_level"] is None
    assert draft.extra["keywords"] == ["quic", "datagram"]
    assert draft.extra["expires"] == "2021-05-01"
    assert draft.extra["updated"] == "2020-11-01"


@pytest.mark.asyncio
async def test_search_sends_both_filters(respx_mock) -> None:
    route = _mock_search(respx_mock)

    await _provider().search("quic", SearchParams(num_results=10))

    assert route.call_count == 2
    params = [call.request.url.params for call in route.calls]
    title_params = next(p for p in params if "title__icontains" in p)
    abstract_params = next(p for p in params if "abstract__icontains" in p)
    assert title_params["title__icontains"] == "quic"
    assert abstract_params["abstract__icontains"] == "quic"
    for sent in params:
        assert sent["type__slug__in"] == "rfc,draft"
        assert sent["format"] == "json"
        # 10 requested results are oversampled to 2x before re-ranking.
        assert sent["limit"] == "20"


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    _mock_search(respx_mock)

    result = await _provider().search("quic datagram", SearchParams(num_results=1))

    assert [r.title for r in result.results] == [
        "An Unreliable Datagram Extension to QUIC",
    ]
    assert result.results[0].rank == 1


@pytest.mark.asyncio
async def test_search_blank_query_skips_requests(respx_mock) -> None:
    route = respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_TITLE_PAYLOAD),
    )

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_tolerates_single_filter_failure(respx_mock) -> None:
    def _handler(request):
        if "title__icontains" in request.url.params:
            return respx.MockResponse(500)
        return respx.MockResponse(200, json=_ABSTRACT_PAYLOAD)

    respx_mock.get(_API_URL).mock(side_effect=_handler)

    result = await _provider().search("quic datagram", SearchParams(num_results=10))

    assert [r.title for r in result.results] == [
        "QUIC Datagrams",
        "An Unreliable Datagram Extension to QUIC",
        "QUIC: A UDP-Based Multiplexed and Secure Transport",
    ]


@pytest.mark.asyncio
async def test_search_raises_when_both_filters_fail(respx_mock) -> None:
    respx_mock.get(_API_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("quic", SearchParams(num_results=5))


@pytest.mark.asyncio
async def test_search_handles_unexpected_payload_shapes(respx_mock) -> None:
    _mock_search(
        respx_mock,
        title_payload=["not", "a", "mapping"],
        abstract_payload={"objects": "nope"},
    )

    result = await _provider().search("quic", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_snippet_is_truncated_to_shared_limit(respx_mock) -> None:
    long_abstract = " ".join(["datagram"] * 200)
    item = dict(_RFC_ITEM, abstract=long_abstract)
    _mock_search(
        respx_mock,
        title_payload={"objects": [item]},
        abstract_payload={"objects": []},
    )

    result = await _provider().search("quic", SearchParams(num_results=5))

    snippet = result.results[0].snippet
    assert len(snippet) <= 400
    assert snippet.startswith(
        "RFC 9221 | Proposed Standard | IETF | 9 pages | datagram",
    )
