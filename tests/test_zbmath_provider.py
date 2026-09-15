"""Unit tests for the zbMATH Open mathematics provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.zbmath import ZbMathProvider

_API_URL = "https://api.zbmath.org/v1/document/_search"

# Placeholder zbMATH substitutes for text it may not redistribute.
_PLACEHOLDER = (
    "zbMATH Open Web Interface contents unavailable due to conflicting licenses."
)

_SERIES = {
    "acronym": None,
    "issue": "2",
    "publisher": "Springer International Publishing, Cham",
    "short_title": "Adv. Appl. Clifford Algebr.",
    "title": "Advances in Applied Clifford Algebras",
    "volume": "20",
    "year": "2010",
}

# Journal article with an arXiv link and a licence-restricted summary.
_ARTICLE = {
    "id": 5789674,
    "identifier": "1198.42006",
    "year": "2010",
    "document_type": {"code": "j", "description": "journal article"},
    "title": {
        "title": "Directional uncertainty principle for quaternion Fourier transform",
        "subtitle": None,
        "original": None,
    },
    "contributors": {"authors": [{"name": "Hitzer, Eckhard M. S."}], "editors": []},
    "source": {"series": [_SERIES], "book": []},
    "msc": [
        {"code": "42A38", "scheme": "msc2020", "text": "Fourier transforms"},
        {"code": "11R52", "scheme": "msc2020", "text": "Quaternion algebras"},
    ],
    "links": [
        {
            "identifier": "10.1007/s00006-009-0175-2",
            "type": "doi",
            "url": "https://doi.org/10.1007/s00006-009-0175-2",
        },
        {
            "identifier": "1306.1276",
            "type": "arxiv",
            "url": "https://arxiv.org/abs/1306.1276",
        },
    ],
    "language": {"languages": ["English"]},
    "editorial_contributions": [
        {"contribution_type": "summary", "text": _PLACEHOLDER},
    ],
    "database": "Zbl",
    "zbmath_url": "https://zbmath.org/5789674",
}

# Book whose series is the venue and whose review carries LaTeX markup.
_BOOK = {
    "id": 7261776,
    "identifier": "1481.11003",
    "year": "2021",
    "document_type": {"code": "b", "description": "book / book article"},
    "title": {"title": "Quaternion algebras", "subtitle": None, "original": None},
    "contributors": {"authors": [{"name": "Voight, John"}], "editors": []},
    "source": {
        "series": [
            {
                "short_title": "Grad. Texts Math.",
                "title": "Graduate Texts in Mathematics",
                "publisher": "Springer, Cham",
                "volume": "288",
            }
        ],
        "book": [{"book_id": 7261776, "publisher": "Cham: Springer", "year": "2021"}],
    },
    "msc": [{"code": "11R52", "scheme": "msc2020", "text": "Quaternion algebras"}],
    "links": [
        {
            "identifier": "10.1007/978-3-030-56694-4",
            "type": "doi",
            "url": "https://doi.org/10.1007/978-3-030-56694-4",
        }
    ],
    "language": {"languages": ["English"]},
    "editorial_contributions": [
        {
            "contribution_type": "review",
            "text": r"The book \emph{under discussion} treats \(\mathrm{SL}(2)\) well.",
        }
    ],
    "database": "Zbl",
    "zbmath_url": "https://zbmath.org/7261776",
}

# Indexed record without a Zbl number: its integer id is the only stable key.
_UNNUMBERED = {
    "id": 7996407,
    "identifier": None,
    "year": "2025",
    "document_type": {"code": "j", "description": "journal article"},
    "title": {
        "title": "Motion, dual quaternion optimization and motion optimization",
        "subtitle": None,
        "original": None,
    },
    "contributors": {"authors": [{"name": "Qi, Liqun"}], "editors": []},
    "source": {"series": [{"short_title": "Commun. Appl. Math. Comput."}], "book": []},
    "msc": [],
    "links": [],
    "language": {"languages": ["English"]},
    "editorial_contributions": [{"contribution_type": "summary", "text": _PLACEHOLDER}],
    "database": "Zbl",
    "zbmath_url": "https://zbmath.org/7996407",
}


def _provider() -> ZbMathProvider:
    """Return a fresh provider instance for each test."""
    return ZbMathProvider()


def _payload(items: object) -> dict[str, object]:
    """Wrap *items* in a zbMATH search response envelope."""
    return {"result": items, "status": {"execution_time": "0.02"}}


def _mock_search(respx_mock, payload: object = None):
    """Register a zbMATH search route and return it."""
    if payload is None:
        payload = _payload([_ARTICLE, _BOOK, _UNNUMBERED])
    return respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=payload),
    )


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "zbmath"
    assert p.tags == ["academic", "web", "math"]
    assert "keyless" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "zbmath" in registry
    assert registry["zbmath"].tags == ["academic", "web", "math"]


def test_clean_collapses_whitespace() -> None:
    assert ZbMathProvider._clean("  a\n b\tc ") == "a b c"
    assert ZbMathProvider._clean(None) == ""
    assert ZbMathProvider._clean("") == ""
    assert ZbMathProvider._clean(2011) == "2011"


def test_plain_strips_latex_markup() -> None:
    assert (
        ZbMathProvider._plain(r"The \emph{book} treats \(\mathrm{SL}(2)\)")
        == "The book treats (SL(2))"
    )
    assert ZbMathProvider._plain("a~b") == "a b"
    assert ZbMathProvider._plain(None) == ""


def test_tokens_lowercases_matches() -> None:
    assert ZbMathProvider._tokens("Quaternion! Algebras?") == ["quaternion", "algebras"]
    assert ZbMathProvider._tokens("---") == []


def test_title_joins_subtitle_and_falls_back_to_original() -> None:
    assert (
        ZbMathProvider._title({"title": {"title": "Main", "subtitle": "Sub"}})
        == "Main: Sub"
    )
    assert ZbMathProvider._title(
        {"title": {"title": None, "original": "Original"}}
    ) == ("Original")
    assert ZbMathProvider._title({"title": "Plain"}) == "Plain"
    assert ZbMathProvider._title({"title": {}}) == ""
    assert ZbMathProvider._title({}) == ""


def test_names_fall_back_to_editors() -> None:
    assert ZbMathProvider._names(_BOOK) == ["Voight, John"]
    editors_only = {
        "contributors": {"authors": [], "editors": [{"name": " Horvat, L. "}]}
    }
    assert ZbMathProvider._names(editors_only) == ["Horvat, L."]
    assert ZbMathProvider._names({"contributors": [{"name": "x"}]}) == []
    assert ZbMathProvider._names({}) == []


def test_venue_prefers_series_then_book_publisher() -> None:
    assert ZbMathProvider._venue(_ARTICLE) == "Adv. Appl. Clifford Algebr."
    publisher_only = {
        "source": {"series": [], "book": [{"publisher": "Cham: Springer"}]}
    }
    assert ZbMathProvider._venue(publisher_only) == "Cham: Springer"
    assert ZbMathProvider._venue({"source": {"series": "nope"}}) == ""
    assert ZbMathProvider._venue({}) == ""


def test_msc_codes_skip_malformed_entries() -> None:
    assert ZbMathProvider._msc(_ARTICLE) == ["42A38", "11R52"]
    assert ZbMathProvider._msc(
        {"msc": [{"code": None}, "nope", {"code": " 01A75 "}]}
    ) == ["01A75"]
    assert ZbMathProvider._msc({}) == []


def test_contribution_skips_licence_placeholder() -> None:
    assert ZbMathProvider._contribution(_ARTICLE) == ("", "")
    assert ZbMathProvider._contribution({}) == ("", "")

    both = {
        "editorial_contributions": [
            {"contribution_type": "editorial", "text": _PLACEHOLDER},
            {"contribution_type": "review", "text": "Review: Solid exposition."},
        ]
    }
    assert ZbMathProvider._contribution(both) == ("Review", "Solid exposition.")


def test_link_identifier_reads_typed_links() -> None:
    assert (
        ZbMathProvider._link_identifier(_ARTICLE, "doi") == "10.1007/s00006-009-0175-2"
    )
    assert ZbMathProvider._link_identifier(_ARTICLE, "arxiv") == "1306.1276"
    assert ZbMathProvider._link_identifier(_ARTICLE, "http") == ""
    assert ZbMathProvider._link_identifier({}, "doi") == ""


def test_language_ignores_placeholder() -> None:
    assert ZbMathProvider._language(_ARTICLE) == "English"
    assert ZbMathProvider._language({"language": {"languages": [_PLACEHOLDER]}}) == ""
    assert ZbMathProvider._language({"language": "English"}) == ""
    assert ZbMathProvider._language({}) == ""


def test_score_rewards_exact_and_prefix_titles() -> None:
    tokens = ZbMathProvider._tokens("quaternion algebras")
    query = "quaternion algebras"
    exact = ZbMathProvider._score("Quaternion Algebras", [], query, tokens)
    prefix = ZbMathProvider._score("Quaternion algebras II", [], query, tokens)
    author = ZbMathProvider._score(
        "Motion optimization", ["Qi, Quaternion"], query, tokens
    )
    assert exact > prefix > author


def test_build_result_skips_titleless_records() -> None:
    assert _provider()._build_result({}) is None
    assert _provider()._build_result({"title": {"title": "   "}}) is None


@pytest.mark.asyncio
async def test_search_ranks_title_match_first_and_dedupes(respx_mock) -> None:
    _mock_search(
        respx_mock,
        _payload([_ARTICLE, _BOOK, _UNNUMBERED, dict(_ARTICLE)]),
    )

    result = await _provider().search(
        "quaternion algebras", SearchParams(num_results=10)
    )

    assert [r.title for r in result.results] == [
        "Quaternion algebras",
        "Directional uncertainty principle for quaternion Fourier transform",
        "Motion, dual quaternion optimization and motion optimization",
    ]
    assert [r.rank for r in result.results] == [1, 2, 3]


@pytest.mark.asyncio
async def test_search_builds_article_result(respx_mock) -> None:
    _mock_search(respx_mock)

    result = await _provider().search("quaternion", SearchParams(num_results=10))
    article = next(r for r in result.results if r.extra["zbl_number"] == "1198.42006")

    assert article.url == "https://zbmath.org/5789674"
    assert article.source == "zbmath.org"
    assert article.provider == "zbmath"
    assert article.published_date == "2010"
    assert article.snippet == (
        "Hitzer, Eckhard M. S. | 2010 | journal article | "
        "Source: Adv. Appl. Clifford Algebr. | Zbl 1198.42006 | "
        "MSC 42A38, 11R52"
    )
    assert article.extra == {
        "zbl_number": "1198.42006",
        "zbmath_id": 5789674,
        "database": "Zbl",
        "document_type": "journal article",
        "authors": ["Hitzer, Eckhard M. S."],
        "year": "2010",
        "source": "Adv. Appl. Clifford Algebr.",
        "msc": ["42A38", "11R52"],
        "review": None,
        "language": "English",
        "doi": "10.1007/s00006-009-0175-2",
        "arxiv_id": "1306.1276",
    }


@pytest.mark.asyncio
async def test_search_builds_book_result(respx_mock) -> None:
    _mock_search(respx_mock)

    result = await _provider().search(
        "quaternion algebras", SearchParams(num_results=10)
    )
    book = result.results[0]

    assert book.title == "Quaternion algebras"
    assert book.snippet.endswith(
        "| Review: The book under discussion treats (SL(2)) well."
    )
    assert book.extra["review"] == "The book under discussion treats (SL(2)) well."
    assert book.extra["source"] == "Grad. Texts Math."
    assert book.extra["doi"] == "10.1007/978-3-030-56694-4"
    assert book.extra["arxiv_id"] is None


@pytest.mark.asyncio
async def test_search_falls_back_to_id_when_zbl_number_missing(respx_mock) -> None:
    _mock_search(respx_mock)

    result = await _provider().search(
        "motion optimization", SearchParams(num_results=10)
    )
    unnumbered = next(r for r in result.results if r.extra["zbmath_id"] == 7996407)

    assert unnumbered.url == "https://zbmath.org/7996407"
    assert unnumbered.extra["zbl_number"] is None
    assert unnumbered.snippet.startswith("Qi, Liqun | 2025 | journal article")


@pytest.mark.asyncio
async def test_search_sends_paging_params(respx_mock) -> None:
    route = _mock_search(respx_mock)

    await _provider().search("quaternion algebras", SearchParams(num_results=20))

    params = route.calls[-1].request.url.params
    assert params["search_string"] == "quaternion algebras"
    # 20 requested results are capped at the page size and oversampled 3x.
    assert params["results_per_page"] == "30"
    assert params["page"] == "0"


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    _mock_search(respx_mock)

    result = await _provider().search(
        "quaternion algebras", SearchParams(num_results=1)
    )

    assert [r.title for r in result.results] == ["Quaternion algebras"]
    assert result.results[0].rank == 1


@pytest.mark.asyncio
async def test_search_blank_query_skips_requests(respx_mock) -> None:
    route = _mock_search(respx_mock)

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_treats_404_as_no_matches(respx_mock) -> None:
    route = respx_mock.get(_API_URL).mock(return_value=respx.MockResponse(404))

    result = await _provider().search("zzzz", SearchParams(num_results=5))

    assert result.results == []
    assert route.called


@pytest.mark.asyncio
async def test_search_raises_on_server_error(respx_mock) -> None:
    respx_mock.get(_API_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await _provider().search("quaternion", SearchParams(num_results=5))


@pytest.mark.asyncio
async def test_search_handles_unexpected_payload_shapes(respx_mock) -> None:
    for payload in (
        {"result": "nope"},
        ["not", "a", "mapping"],
        _payload(["not-a-mapping", {}, {"title": {"title": None}}]),
    ):
        respx_mock.get(_API_URL).mock(
            return_value=respx.MockResponse(200, json=payload),
        )
        result = await _provider().search("quaternion", SearchParams(num_results=5))
        assert result.results == []


@pytest.mark.asyncio
async def test_snippet_is_truncated_to_shared_limit(respx_mock) -> None:
    review = " ".join(["quaternion"] * 200)
    item = dict(
        _BOOK,
        editorial_contributions=[{"contribution_type": "review", "text": review}],
    )
    _mock_search(respx_mock, _payload([item]))

    result = await _provider().search("quaternion", SearchParams(num_results=5))

    snippet = result.results[0].snippet
    assert len(snippet) <= 400
    assert snippet.startswith("Voight, John | 2021 | book / book article |")
    assert "| Review: quaternion quaternion" in snippet
