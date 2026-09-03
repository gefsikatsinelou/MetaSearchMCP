"""Unit tests for the Nobel Prize award search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.nobel import NobelPrizeProvider

_SAMPLE_RESPONSE: dict[str, object] = {
    "nobelPrizes": [
        {
            "awardYear": "1921",
            "category": {"en": "Physics", "id": "phy"},
            "categoryFullName": {"en": "The Nobel Prize in Physics"},
            "dateAwarded": "1922-11-09",
            "laureates": [
                {
                    "knownName": {"en": "Albert Einstein"},
                    "fullName": {"en": "Albert Einstein"},
                    "motivation": {
                        "en": "for his services to Theoretical Physics",
                    },
                },
            ],
        },
        {
            "awardYear": "1921",
            "category": {"en": "Literature", "id": "lit"},
            "categoryFullName": {"en": "The Nobel Prize in Literature"},
            "dateAwarded": "1921-11-10",
            "laureates": [
                {
                    "knownName": {"en": "Anatole France"},
                    "fullName": {"en": "Anatole France"},
                    "motivation": {
                        "en": "in recognition of his brilliant literary achievements",
                    },
                },
            ],
        },
        {
            # Missing awardYear -> skipped.
            "category": {"en": "Peace", "id": "pea"},
        },
    ],
    "meta": {"offset": 0, "limit": 2, "count": 2},
}

_EMPTY_RESPONSE: dict[str, object] = {"nobelPrizes": [], "meta": {"count": 0}}


def _provider() -> NobelPrizeProvider:
    return NobelPrizeProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "nobel"
    assert p.tags == ["reference", "awards", "history"]


def test_year_of() -> None:
    p = _provider()
    assert p._year_of("1921") == "1921"
    assert p._year_of("einstein 1921") == "1921"
    assert p._year_of("physics 2024") == "2024"
    assert p._year_of("latest prizes") is None
    assert p._year_of("in 1800") is None  # before the Nobel era
    assert p._year_of("year 2999") is None  # far future


def test_resolve_category() -> None:
    p = _provider()
    assert p._resolve_category("chemistry") == "che"
    assert p._resolve_category("Physics 1921") == "phy"
    assert p._resolve_category("the nobel prize in literature") == "lit"
    assert p._resolve_category("economic sciences") == "eco"
    assert p._resolve_category("peace prize") == "pea"
    assert p._resolve_category("quantum physics") == "phy"
    assert p._resolve_category("einstein") is None


def test_category_helpers() -> None:
    assert NobelPrizeProvider._category_label("che") == "chemistry"
    assert NobelPrizeProvider._category_label("zzz") == "zzz"
    assert NobelPrizeProvider._category_url("che").startswith(
        "https://www.nobelprize.org/prizes/chemistry/",
    )
    assert NobelPrizeProvider._category_url("zzz") == (
        "https://www.nobelprize.org/prizes/"
    )


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "The Nobel Prize in Physics 1921"
    assert r.url.startswith("https://www.nobelprize.org/prizes/physics/")
    assert "Albert Einstein" in r.snippet
    assert "Theoretical Physics" in r.snippet
    assert r.provider == "nobel"
    assert r.source == "nobelprize.org"
    assert r.rank == 1
    assert r.published_date == "1922-11-09"
    assert r.extra["category"] == "physics"
    assert r.extra["category_id"] == "phy"
    assert r.extra["year"] == "1921"
    assert r.extra["laureates"] == ["Albert Einstein"]
    assert r.extra["payload"]["awardYear"] == "1921"
    assert r.extra["payload"]["category"] == "phy"


def test_parse_full_label_fallback_and_rank() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    # categoryFullName present -> used in the title.
    assert result.results[1].title == "The Nobel Prize in Literature 1921"
    assert result.results[1].rank == 2


def test_parse_skips_prizes_without_year() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert all(r.extra["year"] for r in result.results)


def test_parse_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1
    assert result.results[0].extra["year"] == "1921"


def test_parse_empty_and_malformed() -> None:
    assert _provider()._parse(_EMPTY_RESPONSE).results == []
    assert _provider()._parse({}).results == []
    assert _provider()._parse({"nobelPrizes": ["junk", None, 42]}).results == []
    assert _provider()._parse("junk").results == []
    assert _provider()._parse(None).results == []


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_year_and_category_params(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.nobelprize.org/2.1/nobelPrizes").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search(
        "physics 1921",
        SearchParams(num_results=5),
    )

    assert len(result.results) == 2
    request = respx_mock.calls.last.request
    assert request.url.params["nobelPrizeYear"] == "1921"
    assert request.url.params["nobelPrizeCategory"] == "phy"
    assert request.url.params["sort"] == "desc"


@pytest.mark.asyncio
async def test_search_unresolved_query_falls_back_to_latest(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.nobelprize.org/2.1/nobelPrizes").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search(
        "flying spaghetti monster",
        SearchParams(num_results=5),
    )

    assert result.results == []
    request = respx_mock.calls.last.request
    # No year/category resolved: only limit + sort are sent.
    assert "nobelPrizeYear" not in request.url.params
    assert "nobelPrizeCategory" not in request.url.params
    assert request.url.params["sort"] == "desc"
