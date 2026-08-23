"""Tests for the in-memory TTL search cache and its orchestrator integration."""

from __future__ import annotations

from metasearchmcp.cache import SearchCache, get_search_cache


def _make_search_cache(ttl: float = 60.0, max_entries: int = 10) -> SearchCache:
    """Build an isolated cache instance for a single test."""
    return SearchCache(ttl_seconds=ttl, max_entries=max_entries)


def test_cache_set_and_get_roundtrip():
    cache = _make_search_cache()
    assert cache.get("k") is None
    cache.set("k", {"value": 42})
    assert cache.get("k") == {"value": 42}


def test_cache_get_missing_returns_none():
    cache = _make_search_cache()
    assert cache.get("missing") is None


def test_cache_respects_ttl():
    cache = _make_search_cache(ttl=0.05)
    cache.set("k", "v")
    assert cache.get("k") == "v"
    # Ensure the entry has expired.
    import time

    time.sleep(0.1)
    assert cache.get("k") is None


def test_cache_len_counts_only_live_entries():
    cache = _make_search_cache(ttl=0.05)
    cache.set("a", 1)
    cache.set("b", 2)
    assert len(cache) == 2
    import time

    time.sleep(0.1)
    assert len(cache) == 0


def test_cache_evicts_oldest_when_full():
    cache = _make_search_cache(max_entries=3)
    for i in range(3):
        cache.set(f"key{i}", i)
    # The cache is full; inserting a fourth evicts the oldest (key0).
    cache.set("key3", 3)
    assert cache.get("key0") is None
    assert cache.get("key1") == 1
    assert cache.get("key2") == 2
    assert cache.get("key3") == 3


def test_cache_recent_get_avoids_eviction():
    cache = _make_search_cache(max_entries=2)
    cache.set("a", 1)
    cache.set("b", 2)
    # Touching "a" refreshes its recency.
    assert cache.get("a") == 1
    cache.set("c", 3)
    # "b" (least recently used) is evicted, "a" survives.
    assert cache.get("a") == 1
    assert cache.get("b") is None
    assert cache.get("c") == 3


def test_cache_clear_removes_all():
    cache = _make_search_cache()
    cache.set("a", 1)
    cache.set("b", 2)
    cache.clear()
    assert len(cache) == 0
    assert cache.get("a") is None


def test_cache_stats_shape_and_insertion_counter():
    cache = _make_search_cache(ttl=60.0, max_entries=10)
    stats = cache.stats()
    assert stats == {
        "entries": 0,
        "max_entries": 10,
        "ttl_seconds": 60.0,
        "insertions": 0,
    }

    cache.set("a", 1)
    cache.set("b", 2)
    # Overwriting an existing key still counts as a new insertion.
    cache.set("a", 3)
    stats = cache.stats()
    assert stats["entries"] == 2
    assert stats["insertions"] == 3

    cache.clear()
    stats = cache.stats()
    # Clearing resets the occupancy but not the monotonic insertion counter.
    assert stats["entries"] == 0
    assert stats["insertions"] == 3


def test_cache_stats_purges_expired_entries_without_side_effects():
    import time

    cache = _make_search_cache(ttl=0.05)
    cache.set("a", 1)
    cache.set("b", 2)
    time.sleep(0.1)

    stats = cache.stats()
    assert stats["entries"] == 0
    assert stats["insertions"] == 2
    # Expired entries are gone; the counter is unaffected by expiry.
    assert cache.get("a") is None
    assert cache.get("b") is None


def test_cache_overwrite_updates_value():
    cache = _make_search_cache()
    cache.set("k", "old")
    cache.set("k", "new")
    assert cache.get("k") == "new"


def test_get_search_cache_returns_singleton():
    from metasearchmcp.cache import _search_cache

    assert get_search_cache() is _search_cache


# ---------------------------------------------------------------------------
# Orchestrator integration
# ---------------------------------------------------------------------------


async def test_run_search_plan_caches_and_serves_from_cache():
    """A repeated identical search is served from cache without re-running."""
    from unittest.mock import AsyncMock, MagicMock

    from metasearchmcp.cache import _search_cache
    from metasearchmcp.orchestrator import run_search_plan

    provider = MagicMock()
    provider.name = "fake"
    provider.tags = ["web"]
    provider.search = AsyncMock(
        return_value=MagicMock(
            results=[],
            related_searches=[],
            suggestions=[],
            answer_box=None,
        ),
    )

    _search_cache.clear()

    await run_search_plan("q", [provider])
    await run_search_plan("q", [provider])

    # The provider.search should not be called on the cached second hit.
    assert provider.search.await_count == 1
    _search_cache.clear()


async def test_run_search_plan_cache_disabled_skips_caching():
    """When cache is disabled, every call re-runs the provider."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from metasearchmcp.cache import _search_cache
    from metasearchmcp.config import Settings
    from metasearchmcp.orchestrator import run_search_plan

    provider = MagicMock()
    provider.name = "fake"
    provider.tags = ["web"]
    provider.search = AsyncMock(
        return_value=MagicMock(
            results=[],
            related_searches=[],
            suggestions=[],
            answer_box=None,
        ),
    )

    _search_cache.clear()

    with patch(
        "metasearchmcp.orchestrator.get_settings",
        return_value=Settings(cache_enabled=False),
    ):
        await run_search_plan("q", [provider])
        await run_search_plan("q", [provider])

    assert provider.search.await_count == 2
    _search_cache.clear()
