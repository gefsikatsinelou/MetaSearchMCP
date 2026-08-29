"""Tests for the orchestrator's provider retry behavior."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from metasearchmcp.contracts import ProviderPayload, SearchHit, SearchOptions
from metasearchmcp.orchestrator import execute_provider_search, run_search_plan


def _result(url: str, provider: str) -> SearchHit:
    return SearchHit(title="T", url=url, provider=provider)


def _flaky_provider(name: str, failures: int = 1):
    """Return a provider that fails the first *failures* calls, then succeeds."""
    provider = MagicMock()
    provider.name = name
    provider.tags = []
    calls = {"count": 0}

    async def _search(query, params):
        calls["count"] += 1
        if calls["count"] <= failures:
            raise RuntimeError(f"{name} transient failure")
        return ProviderPayload(results=[_result("https://ok.com", name)])

    provider.search = _search
    provider._call_count = calls
    return provider


@pytest.mark.asyncio
async def test_execute_provider_search_retries_then_succeeds():
    """A provider failing once should succeed when retried."""
    provider = _flaky_provider("flaky", failures=1)
    name, payload, _latency_ms, error = await execute_provider_search(
        provider,
        "test",
        SearchOptions(),
        timeout_seconds=5.0,
        retries=1,
        backoff_seconds=0.01,
    )
    assert name == "flaky"
    assert error is None
    assert payload is not None
    assert payload.results[0].url == "https://ok.com"
    assert provider._call_count["count"] == 2


@pytest.mark.asyncio
async def test_execute_provider_search_no_retries_by_default():
    """Without retries, a single failure should be reported immediately."""
    provider = _flaky_provider("flaky", failures=1)
    name, payload, _latency_ms, error = await execute_provider_search(
        provider,
        "test",
        SearchOptions(),
        timeout_seconds=5.0,
    )
    assert name == "flaky"
    assert error == "flaky transient failure"
    assert payload is None
    assert provider._call_count["count"] == 1


@pytest.mark.asyncio
async def test_execute_provider_search_gives_up_after_exhausting_retries():
    """Persistently failing providers should report the final error."""
    provider = _flaky_provider("always", failures=99)
    name, payload, _latency_ms, error = await execute_provider_search(
        provider,
        "test",
        SearchOptions(),
        timeout_seconds=5.0,
        retries=2,
        backoff_seconds=0.01,
    )
    assert name == "always"
    assert payload is None
    assert error == "always transient failure"
    assert provider._call_count["count"] == 3  # 1 initial + 2 retries


@pytest.mark.asyncio
async def test_run_search_plan_retries_provider(monkeypatch):
    """run_search_plan should apply configured retries to provider calls."""
    from metasearchmcp import orchestrator

    provider = _flaky_provider("flaky", failures=1)

    class FakeSettings:
        aggregator_timeout = 5.0
        provider_retries = 1
        retry_backoff_seconds = 0.01
        cache_enabled = False

    monkeypatch.setattr(orchestrator, "get_settings", lambda: FakeSettings())

    resp = await run_search_plan("test", [provider])
    assert resp.results[0].url == "https://ok.com"
    assert resp.providers[0].success is True
    assert provider._call_count["count"] == 2


@pytest.mark.asyncio
async def test_run_search_plan_retry_disabled_by_default(monkeypatch):
    """With provider_retries=0 a failing provider is reported as failed."""
    from metasearchmcp import orchestrator

    provider = _flaky_provider("flaky", failures=1)

    class FakeSettings:
        aggregator_timeout = 5.0
        provider_retries = 0
        retry_backoff_seconds = 0.01
        cache_enabled = False

    monkeypatch.setattr(orchestrator, "get_settings", lambda: FakeSettings())

    resp = await run_search_plan("test", [provider])
    assert resp.results == []
    assert resp.providers[0].success is False
    assert provider._call_count["count"] == 1


@pytest.mark.asyncio
async def test_retry_does_not_duplicate_results():
    """A retried successful call must not merge duplicate hits into the report."""
    provider = _flaky_provider("flaky", failures=1)
    _name, payload, _latency_ms, error = await execute_provider_search(
        provider,
        "test",
        SearchOptions(),
        timeout_seconds=5.0,
        retries=1,
        backoff_seconds=0.01,
    )
    assert error is None
    assert len(payload.results) == 1
