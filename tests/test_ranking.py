"""Tests for consensus-based result ranking and its orchestrator integration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from metasearchmcp.contracts import SearchHit
from metasearchmcp.providers.base import BaseProvider
from metasearchmcp.ranking import (
    count_consensus,
    rank_and_dedup_results,
    rank_results,
)


def _hit(
    url: str,
    title: str = "T",
    provider: str = "p",
    rank: int = 0,
) -> SearchHit:
    """Build a SearchHit with the given attributes."""
    return SearchHit(title=title, url=url, provider=provider, rank=rank)


def _provider(name: str, search) -> MagicMock:
    """Build a mock provider with a fixed name and coroutine search handler."""
    provider = MagicMock(spec=BaseProvider)
    provider.name = name
    provider.search = search
    provider.tags = []
    return provider


# --- count_consensus ---


def test_count_consensus_counts_per_canonical_url():
    hits = [
        _hit("https://a.com", provider="p1"),
        _hit("https://a.com", provider="p2"),
        _hit("https://b.com", provider="p1"),
    ]
    consensus = count_consensus(hits)
    assert consensus["a.com/"] == 2
    assert consensus["b.com/"] == 1


def test_count_consensus_tracking_params_collapse():
    hits = [
        _hit("https://a.com/foo?utm_source=x", provider="p1"),
        _hit("https://a.com/foo", provider="p2"),
    ]
    consensus = count_consensus(hits)
    assert len(consensus) == 1
    assert consensus["a.com/foo"] == 2


def test_count_consensus_skips_empty_urls():
    assert count_consensus([_hit("", provider="p1")]) == {}


# --- rank_results ---


def test_rank_results_empty_input():
    assert rank_results([], "q") == []


def test_rank_results_term_match_ranks_first():
    hits = [
        _hit("https://unrelated.com", title="Random blog post"),
        _hit("https://python.org", title="Python programming language"),
    ]
    ranked = rank_results(hits, "python")
    assert ranked[0].url == "https://python.org"


def test_rank_results_stable_tiebreak_preserves_input_order():
    hits = [_hit("https://a.com"), _hit("https://b.com")]
    ranked = rank_results(hits, "unrelated query")
    assert [h.url for h in ranked] == ["https://a.com", "https://b.com"]


# --- rank_and_dedup_results ---


def test_rank_and_dedup_collapses_duplicates():
    hits = [
        _hit("https://a.com", provider="p1"),
        _hit("https://a.com", provider="p2"),
        _hit("https://b.com", provider="p1"),
    ]
    ranked = rank_and_dedup_results(hits, "q", max_results=10)
    urls = [h.url for h in ranked]
    assert urls.count("https://a.com") == 1
    assert len(ranked) == 2


def test_rank_and_dedup_consensus_boost_beats_single_provider():
    """A URL corroborated by two providers outranks an uncorroborated one."""
    hits = [
        _hit("https://single.com", title="plain", provider="p1"),
        _hit("https://both.com", title="plain", provider="p1"),
        _hit("https://both.com", title="plain", provider="p2"),
    ]
    ranked = rank_and_dedup_results(hits, "zzz", max_results=10)
    assert ranked[0].url == "https://both.com"
    assert ranked[1].url == "https://single.com"


def test_rank_and_dedup_query_term_within_consensus():
    """Query relevance breaks ties among equally corroborated results."""
    hits = [
        _hit("https://both-a.com", title="exact python match", provider="p1"),
        _hit("https://both-a.com", title="exact python match", provider="p2"),
        _hit("https://both-b.com", title="nothing relevant", provider="p1"),
        _hit("https://both-b.com", title="nothing relevant", provider="p2"),
    ]
    ranked = rank_and_dedup_results(hits, "python", max_results=10)
    assert ranked[0].url == "https://both-a.com"
    assert ranked[1].url == "https://both-b.com"


def test_rank_and_dedup_caps_results():
    hits = [_hit(f"https://site{i}.com") for i in range(5)]
    ranked = rank_and_dedup_results(hits, "q", max_results=2)
    assert len(ranked) == 2


def test_rank_and_dedup_no_cap_when_max_non_positive():
    hits = [_hit(f"https://site{i}.com") for i in range(3)]
    ranked = rank_and_dedup_results(hits, "q", max_results=0)
    assert len(ranked) == 3


# --- orchestrator integration ---


@pytest.mark.asyncio
async def test_orchestrator_reorders_by_consensus_when_enabled(monkeypatch):
    """With RANK_RESULTS enabled the orchestrator reorders merged hits."""
    from metasearchmcp import orchestrator
    from metasearchmcp.contracts import ProviderPayload, SearchOptions
    from metasearchmcp.orchestrator import run_search_plan

    async def p1_search(query, params):
        return ProviderPayload(
            results=[
                _hit("https://only-p1.com", provider="p1"),
                _hit("https://both.com", provider="p1"),
            ],
        )

    async def p2_search(query, params):
        return ProviderPayload(results=[_hit("https://both.com", provider="p2")])

    p1 = _provider("p1", p1_search)
    p2 = _provider("p2", p2_search)

    class FakeSettings:
        aggregator_timeout = 5.0
        rank_results = True
        cache_enabled = False

    monkeypatch.setattr(orchestrator, "get_settings", lambda: FakeSettings())

    resp = await run_search_plan(
        "q",
        [p1, p2],
        SearchOptions(num_results=10, max_total_results=10),
    )
    urls = [h.url for h in resp.results]
    # both.com was corroborated by two providers, so it ranks first.
    assert urls == ["https://both.com", "https://only-p1.com"]
    assert [h.rank for h in resp.results] == [1, 2]


@pytest.mark.asyncio
async def test_orchestrator_keeps_provider_order_when_disabled(monkeypatch):
    """With RANK_RESULTS off the orchestrator keeps provider-priority order."""
    from metasearchmcp import orchestrator
    from metasearchmcp.contracts import ProviderPayload, SearchOptions
    from metasearchmcp.orchestrator import run_search_plan

    async def p1_search(query, params):
        return ProviderPayload(
            results=[
                _hit("https://only-p1.com", provider="p1"),
                _hit("https://both.com", provider="p1"),
            ],
        )

    async def p2_search(query, params):
        return ProviderPayload(results=[_hit("https://both.com", provider="p2")])

    p1 = _provider("p1", p1_search)
    p2 = _provider("p2", p2_search)

    class FakeSettings:
        aggregator_timeout = 5.0
        rank_results = False
        cache_enabled = False

    monkeypatch.setattr(orchestrator, "get_settings", lambda: FakeSettings())

    resp = await run_search_plan(
        "q",
        [p1, p2],
        SearchOptions(num_results=10, max_total_results=10),
    )
    urls = [h.url for h in resp.results]
    assert urls == ["https://only-p1.com", "https://both.com"]
