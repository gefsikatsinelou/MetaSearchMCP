"""Tests for the orchestration layer: concurrency, failures, and merging."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from metasearchmcp.contracts import ProviderPayload, SearchHit, SearchOptions
from metasearchmcp.orchestrator import run_search_plan


def _make_provider(
    name: str, results: list[SearchHit], fail: bool = False, delay: float = 0.0,
):
    """Create a minimal mock provider."""
    provider = MagicMock()
    provider.name = name
    provider.tags = []

    async def _search(query, params):
        if delay:
            await asyncio.sleep(delay)
        if fail:
            raise RuntimeError(f"{name} failed")
        return ProviderPayload(results=results)

    provider.search = _search
    return provider


def _result(url: str, provider: str) -> SearchHit:
    return SearchHit(title="T", url=url, provider=provider)


@pytest.mark.asyncio
async def test_aggregate_combines_results():
    p1 = _make_provider(
        "p1", [_result("https://a.com", "p1"), _result("https://b.com", "p1")],
    )
    p2 = _make_provider("p2", [_result("https://c.com", "p2")])

    resp = await run_search_plan("test", [p1, p2])
    assert len(resp.results) == 3
    urls = {r.url for r in resp.results}
    assert urls == {"https://a.com", "https://b.com", "https://c.com"}


@pytest.mark.asyncio
async def test_aggregate_partial_failure_does_not_abort():
    good = _make_provider("good", [_result("https://ok.com", "good")])
    bad = _make_provider("bad", [], fail=True)

    resp = await run_search_plan("test", [good, bad])
    assert len(resp.results) == 1
    assert resp.results[0].url == "https://ok.com"

    statuses = {s.name: s for s in resp.providers}
    assert statuses["good"].success is True
    assert statuses["bad"].success is False
    assert "failed" in statuses["bad"].error
    assert resp.errors == ["bad: bad failed"]


@pytest.mark.asyncio
async def test_aggregate_merges_suggestions():
    p1 = _make_provider("p1", [_result("https://a.com", "p1")])
    p2 = _make_provider("p2", [_result("https://b.com", "p2")])

    async def p1_search(query, params):
        return ProviderPayload(
            results=[_result("https://a.com", "p1")],
            suggestions=["python asyncio tutorial", "python taskgroup"],
        )

    async def p2_search(query, params):
        return ProviderPayload(
            results=[_result("https://b.com", "p2")],
            suggestions=["python taskgroup", "python async await"],
        )

    p1.search = p1_search
    p2.search = p2_search

    resp = await run_search_plan("test", [p1, p2])
    assert resp.suggestions == [
        "python asyncio tutorial",
        "python taskgroup",
        "python async await",
    ]


@pytest.mark.asyncio
async def test_aggregate_cleans_related_searches_and_suggestions():
    p = _make_provider("p1", [_result("https://a.com", "p1")])

    async def p_search(query, params):
        return ProviderPayload(
            results=[_result("https://a.com", "p1")],
            related_searches=[" python ", "python", "   "],
            suggestions=[" asyncio ", "asyncio", ""],
        )

    p.search = p_search

    resp = await run_search_plan("test", [p])
    assert resp.related_searches == ["python"]
    assert resp.suggestions == ["asyncio"]


@pytest.mark.asyncio
async def test_aggregate_all_fail_returns_empty():
    bad1 = _make_provider("b1", [], fail=True)
    bad2 = _make_provider("b2", [], fail=True)

    resp = await run_search_plan("test", [bad1, bad2])
    assert resp.results == []
    assert all(not s.success for s in resp.providers)


@pytest.mark.asyncio
async def test_aggregate_deduplicates_across_providers():
    p1 = _make_provider("p1", [_result("https://a.com", "p1")])
    p2 = _make_provider(
        "p2", [_result("https://a.com", "p2"), _result("https://b.com", "p2")],
    )

    resp = await run_search_plan("test", [p1, p2])
    # a.com should appear only once (from p1, which was ordered first)
    urls = [r.url for r in resp.results]
    assert urls.count("https://a.com") == 1
    assert len(resp.results) == 2


@pytest.mark.asyncio
async def test_aggregate_provider_status_includes_latency():
    p = _make_provider("p1", [_result("https://x.com", "p1")], delay=0.01)
    resp = await run_search_plan("test", [p])

    status = resp.providers[0]
    assert status.name == "p1"
    assert status.latency_ms >= 10


@pytest.mark.asyncio
async def test_aggregate_uses_aggregator_timeout(monkeypatch):
    from metasearchmcp import orchestrator

    p = _make_provider("slow", [_result("https://x.com", "slow")], delay=0.02)

    class FakeSettings:
        aggregator_timeout = 0.001

    monkeypatch.setattr(orchestrator, "get_settings", lambda: FakeSettings())

    resp = await run_search_plan("test", [p])

    assert resp.results == []
    assert resp.providers[0].name == "slow"
    assert resp.providers[0].success is False
    assert "timeout after 0.001s" == resp.providers[0].error


@pytest.mark.asyncio
async def test_aggregate_empty_providers():
    resp = await run_search_plan("test", [])
    assert resp.results == []
    assert resp.providers == []


@pytest.mark.asyncio
async def test_aggregate_respects_max_total_results():
    p1 = _make_provider(
        "p1",
        [
            _result("https://a.com", "p1"),
            _result("https://b.com", "p1"),
        ],
    )
    p2 = _make_provider(
        "p2",
        [
            _result("https://c.com", "p2"),
            _result("https://d.com", "p2"),
        ],
    )

    resp = await run_search_plan(
        "test",
        [p1, p2],
        SearchOptions(num_results=10, max_total_results=3),
    )

    assert [result.url for result in resp.results] == [
        "https://a.com",
        "https://b.com",
        "https://c.com",
    ]
    assert [result.rank for result in resp.results] == [1, 2, 3]
