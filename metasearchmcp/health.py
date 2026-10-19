"""Active provider health probes.

``BaseProvider.is_available()`` only reports configuration-level readiness
(e.g. whether a required API key is present). That is cheap but cannot tell
whether an upstream API is actually reachable. This module adds an *active*
probe: a single, minimal search request per provider, bounded by a timeout
and executed concurrently, so callers can distinguish "configured" from
"working".

Only the standard library plus the shared provider interface is used, so the
probe can be reused by the HTTP API, the broker, or scripts.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from metasearchmcp.contracts import SearchOptions

if TYPE_CHECKING:
    from collections.abc import Sequence

    from metasearchmcp.providers.base import BaseProvider

__all__ = [
    "DEFAULT_MAX_PROBES",
    "DEFAULT_PROBE_QUERY",
    "DEFAULT_PROBE_TIMEOUT",
    "probe_provider",
    "probe_providers",
]

DEFAULT_PROBE_QUERY = "test"
DEFAULT_PROBE_TIMEOUT = 5.0
DEFAULT_MAX_PROBES = 10

# Keep upstream payloads tiny: the probe only needs to know whether the
# provider answered, not how good its answers are.
_PROBE_OPTIONS = SearchOptions(num_results=1, max_total_results=1)


async def probe_provider(
    provider: BaseProvider,
    query: str = DEFAULT_PROBE_QUERY,
    timeout_seconds: float = DEFAULT_PROBE_TIMEOUT,
) -> dict[str, Any]:
    """Run one minimal search against *provider* and report the outcome.

    The returned mapping carries ``status`` set to one of ``"ok"``,
    ``"error"``, ``"timeout"``, or ``"unavailable"``. All exceptions are
    caught, so a single broken provider can never abort a health sweep.
    """
    entry: dict[str, Any] = {
        "name": provider.name,
        "description": provider.description,
        "tags": sorted(provider.tags),
        "available": provider.is_available(),
        "status": "unavailable",
        "latency_ms": 0.0,
        "result_count": 0,
        "error": None,
    }
    if not entry["available"]:
        # Missing configuration (e.g. API key): do not bother the upstream.
        return entry

    started = time.monotonic()
    try:
        payload = await asyncio.wait_for(
            provider.search(query, _PROBE_OPTIONS),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        entry["status"] = "timeout"
        entry["error"] = f"timeout after {timeout_seconds}s"
    except Exception as exc:  # a probe must never raise
        entry["status"] = "error"
        entry["error"] = str(exc) or type(exc).__name__
    else:
        entry["status"] = "ok"
        entry["result_count"] = len(payload.results)
    entry["latency_ms"] = round((time.monotonic() - started) * 1000, 1)
    return entry


async def probe_providers(
    providers: Sequence[BaseProvider],
    query: str = DEFAULT_PROBE_QUERY,
    timeout_seconds: float = DEFAULT_PROBE_TIMEOUT,
    max_providers: int = DEFAULT_MAX_PROBES,
) -> dict[str, Any]:
    """Probe up to *max_providers* providers concurrently and summarise.

    Providers are probed in name order so responses are stable, and any
    provider beyond *max_providers* is listed in ``skipped`` instead of being
    contacted. The aggregate ``status`` is ``"degraded"`` when at least one
    probed provider timed out or errored, and ``"ok"`` otherwise.
    """
    selected = sorted(providers, key=lambda provider: provider.name)
    limit = max(1, int(max_providers))
    to_probe = selected[:limit]

    entries = await asyncio.gather(
        *(probe_provider(p, query, timeout_seconds) for p in to_probe),
    )

    ok_count = sum(1 for entry in entries if entry["status"] == "ok")
    unavailable_count = sum(1 for entry in entries if entry["status"] == "unavailable")
    failed_count = len(entries) - ok_count - unavailable_count

    return {
        "status": "ok" if failed_count == 0 else "degraded",
        "query": query,
        "timeout_seconds": timeout_seconds,
        "total": len(selected),
        "probed": len(entries),
        "ok_count": ok_count,
        "failed_count": failed_count,
        "unavailable_count": unavailable_count,
        "skipped": [provider.name for provider in selected[limit:]],
        "providers": entries,
    }
