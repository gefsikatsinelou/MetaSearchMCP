"""In-memory TTL cache for aggregated search results.

Caching avoids re-hitting external providers when the same query + provider
set + options arrive again within a short window (e.g. an agent retrying or
a caller polling). The cache is deliberately simple and bounded:

  * Entries expire after ``cache_ttl`` seconds.
  * The cache is capped at ``cache_max_entries`` items (FIFO eviction).
  * Thread-safety is provided by a single module-level lock.

This module intentionally uses only the standard library so it can be dropped
into the broker, the HTTP API, or the CLI without extra dependencies.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

__all__ = ["SearchCache", "get_search_cache"]

_DEFAULT_TTL_SECONDS = 300.0
_DEFAULT_MAX_ENTRIES = 512


class SearchCache:
    """A minimal thread-safe FIFO TTL cache keyed by search parameters."""

    def __init__(
        self,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
    ) -> None:
        self.ttl = float(ttl_seconds)
        self._max_entries = max(1, int(max_entries))
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self._insertions = 0

    def get(self, key: str) -> Any | None:
        """Return the cached value for *key* if unexpired, else ``None``."""
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            expires_at, value = item
            if time.monotonic() > expires_at:
                self._store.pop(key, None)
                return None
            # Refresh recency so hot keys are less likely to be evicted.
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value: Any) -> None:
        """Store *value* under *key* with the configured TTL."""
        with self._lock:
            self._store[key] = (time.monotonic() + self.ttl, value)
            self._store.move_to_end(key)
            self._insertions += 1
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    def clear(self) -> None:
        """Remove all entries from the cache."""
        with self._lock:
            self._store.clear()

    def stats(self) -> dict[str, Any]:
        """Return a snapshot of cache statistics.

        The snapshot includes the number of live (unexpired) entries, the
        configured TTL, the maximum capacity, and the total number of keys
        ever inserted since the cache was created (a monotonic counter that
        is never reset by expiry or eviction).

        This method is read-only: expired entries are purged, but no key is
        inserted, refreshed, or evicted as a side effect of taking the
        snapshot, so it can safely be exposed through the API.
        """
        with self._lock:
            now = time.monotonic()
            expired = [k for k, (ts, _) in self._store.items() if ts <= now]
            for key in expired:
                self._store.pop(key, None)
            return {
                "entries": len(self._store),
                "max_entries": self._max_entries,
                "ttl_seconds": self.ttl,
                "insertions": self._insertions,
            }

    def __len__(self) -> int:
        """Return the number of live (unexpired) entries."""
        with self._lock:
            now = time.monotonic()
            expired = [k for k, (ts, _) in self._store.items() if ts <= now]
            for key in expired:
                self._store.pop(key, None)
            return len(self._store)


# Module-level singleton shared across the broker, routes, and orchestrator.
_search_cache = SearchCache()


def get_search_cache() -> SearchCache:
    """Return the shared application-wide search cache singleton."""
    return _search_cache
