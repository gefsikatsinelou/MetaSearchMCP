"""Shared pytest fixtures for the MetaSearchMCP test suite."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_search_cache():
    """Reset the shared in-memory search cache before every test.

    The search cache is a process-wide singleton. Because unit tests reuse the
    same query + provider names across call sites, a leftover cached report
    would otherwise leak between tests and make their assertions order-dependent.
    """
    from metasearchmcp.cache import get_search_cache

    get_search_cache().clear()
    yield
    get_search_cache().clear()
