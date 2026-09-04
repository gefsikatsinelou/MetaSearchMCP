"""Unit tests for the Figshare research-data search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.figshare import FigshareProvider

_SAMPLE_RESPONSE: list[dict[str, object]] = [
    {
        "id": 33432910,
        "title": "Post-Quantum Secure Lattice-Based Authentication Scheme",
        "url": "https://api.figshare.com/v2/articles/33432910",
        "url_public_html": (
            "https://figshare.com/articles/journal_contribution/"
            "Post-Quantum_Secure_Lattice-Based_Authentication_Scheme/33432910"
        ),
        "doi": "10.1109/JIOT.2026.3709484",
        "defined_type_name": "journal contribution",
        "description": "A quantum-resistant authentication scheme for IoT devices.",
        "published_date": "2026-09-04T02:22:56Z",
    },
    {
        "id": 30041044,
        "title": "City Liveability Scorecard",
        "url_public_html": "https://figshare.com/articles/report/30041044",
        "url": "https://api.figshare.com/v2/articles/30041044",
        "doi": "",
        "defined_type_name": "report",
        "description": None,
        "published_date": None,
    },
    {
        # Missing title -> skipped.
        "id": 999,
        "defined_type_name": "figure",
    },
    "junk",
]

_EMPTY_RESPONSE: list[dict[str, object]] = []


def _provider() -> FigshareProvider:
    return FigshareProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "figshare"
    assert p.tags == ["academic", "web", "datasets", "repositories"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Post-Quantum Secure Lattice-Based Authentication Scheme"
    assert r.url.startswith("https://figshare.com/articles/")
    assert "quantum-resistant" in r.snippet
    assert r.provider == "figshare"
    assert r.source == "figshare.com"
    assert r.rank == 1
    assert r.published_date == "2026-09-04"
    assert r.extra["doi"] == "10.1109/JIOT.2026.3709484"
    assert r.extra["item_type"] == "journal contribution"
    assert r.extra["published_date_full"] == "2026-09-04T02:22:56Z"


def test_parse_missing_optional_fields() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    r = result.results[1]
    assert r.published_date is None
    assert r.snippet == ""
    assert r.extra["doi"] == ""
    assert r.extra["published_date_full"] == ""
    assert r.extra["item_type"] == "report"
    assert r.rank == 2


def test_parse_skips_titleless_and_non_dict_items() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    # The titleless item and the "junk" string are both skipped.
    assert all(r.title for r in result.results)


def test_parse_limit_and_empty() -> None:
    p = _provider()
    assert len(p._parse(_SAMPLE_RESPONSE, max_results=1).results) == 1
    assert p._parse(_EMPTY_RESPONSE).results == []
    assert p._parse({}).results == []
    assert p._parse("junk").results == []
    assert p._parse(None).results == []


def test_parse_snippet_capped_at_shared_limit() -> None:
    from metasearchmcp.providers.base import MAX_SNIPPET_LENGTH

    long_description = "x" * (MAX_SNIPPET_LENGTH + 200)
    result = _provider()._parse([{"title": "Long", "description": long_description}])
    assert len(result.results[0].snippet) == MAX_SNIPPET_LENGTH


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_query_params(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.figshare.com/v2/articles").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    result = await _provider().search(
        "quantum computing",
        SearchParams(num_results=5),
    )

    assert len(result.results) == 2
    request = respx_mock.calls.last.request
    assert request.url.params["search_for"] == "quantum computing"
    assert request.url.params["page_size"] == "5"
