"""Search orchestrator: execute queries across providers and merge results."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from metasearchmcp.cache import get_search_cache
from metasearchmcp.config import get_settings
from metasearchmcp.contracts import (
    ProviderPayload,
    ProviderReport,
    SearchOptions,
    SearchReport,
)
from metasearchmcp.merge import collapse_duplicate_hits
from metasearchmcp.ranking import rank_and_dedup_results

if TYPE_CHECKING:
    from collections.abc import Sequence

    from metasearchmcp.providers.base import BaseProvider


async def execute_provider_search(
    provider: BaseProvider,
    query: str,
    options: SearchOptions,
    timeout_seconds: float,
    retries: int = 0,
    backoff_seconds: float = 0.3,
) -> tuple[str, ProviderPayload | None, float, str | None]:
    """Run a single provider search with a timeout and return normalized results.

    Transient failures (timeouts, network errors, HTTP 5xx/429) are retried
    up to *retries* extra times with an exponential backoff starting at
    *backoff_seconds*, so a briefly flaky provider does not permanently
    fail a search. Final errors are returned as a string; no exception
    escapes this function.
    """
    attempts = max(0, retries) + 1
    start = time.monotonic()
    payload: ProviderPayload | None = None
    last_error: str | None = None
    for attempt in range(attempts):
        try:
            payload = await asyncio.wait_for(
                provider.search(query, options),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            last_error = f"timeout after {timeout_seconds}s"
        except Exception as exc:
            last_error = str(exc) or type(exc).__name__
        else:
            last_error = None
            break
        if attempt < attempts - 1:
            await asyncio.sleep(min(backoff_seconds * (2**attempt), 2.0))
    latency_ms = (time.monotonic() - start) * 1000
    return provider.name, payload, latency_ms, last_error


def _unique_strings(values: list[str]) -> list[str]:
    """Return a deduplicated list of non-empty, stripped strings in input order."""
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique


def _cache_key(
    query: str,
    providers: Sequence[BaseProvider],
    options: SearchOptions,
) -> str:
    """Build a stable cache key from the query, provider set, and options.

    Provider order is significant (earlier providers take priority during
    deduplication), so it is preserved in the key by using the original
    input order.
    """
    provider_names = "|".join(p.name for p in providers)
    options_part = "|".join(
        [
            f"n={options.num_results}",
            f"m={options.max_total_results}",
            options.language,
            options.country,
            f"s={int(options.safe_search)}",
        ],
    )
    return f"{query}\x1f{provider_names}\x1f{options_part}"


async def run_search_plan(
    query: str,
    providers: Sequence[BaseProvider],
    options: SearchOptions | None = None,
) -> SearchReport:
    """Execute *query* across all *providers* and merge the results.

    Results are deduplicated, capped to ``options.max_total_results``,
    and enriched with per-provider timing and error metadata.

    Identical requests (same query, provider set, and options) are served
    from an in-memory TTL cache when available, avoiding redundant work.
    """
    if options is None:
        options = SearchOptions()

    settings = get_settings()
    cache_enabled = getattr(settings, "cache_enabled", True)
    cache = get_search_cache() if cache_enabled else None
    if cache is not None:
        cache.ttl = getattr(settings, "cache_ttl", 300.0)
        cache_key = _cache_key(query, providers, options)
        cached = cache.get(cache_key)
        if cached is not None:
            return SearchReport.model_validate(cached)

    started_at = time.monotonic()
    jobs = [
        execute_provider_search(
            provider,
            query,
            options,
            settings.aggregator_timeout,
            retries=getattr(settings, "provider_retries", 0),
            backoff_seconds=getattr(settings, "retry_backoff_seconds", 0.3),
        )
        for provider in providers
    ]
    raw_results = await asyncio.gather(*jobs)

    merged_hits = []
    related_searches: list[str] = []
    suggestions: list[str] = []
    provider_reports: list[ProviderReport] = []
    errors: list[str] = []
    answer_box = None

    for provider_name, payload, latency_ms, error in raw_results:
        if payload is None:
            if error:
                errors.append(f"{provider_name}: {error}")
            provider_reports.append(
                ProviderReport(
                    name=provider_name,
                    success=False,
                    latency_ms=round(latency_ms, 1),
                    error=error,
                ),
            )
            continue

        merged_hits.extend(payload.results)
        related_searches.extend(payload.related_searches)
        suggestions.extend(payload.suggestions)
        if answer_box is None and payload.answer_box:
            answer_box = payload.answer_box
        provider_reports.append(
            ProviderReport(
                name=provider_name,
                success=True,
                result_count=len(payload.results),
                latency_ms=round(latency_ms, 1),
            ),
        )

    # Re-rank the raw merged hits by consensus (number of providers that
    # returned the same canonical URL) and query-term relevance, so results
    # corroborated by several independent providers surface above the
    # provider-priority order. Enabled via the RANK_RESULTS setting. This
    # performs its own deduplication, so it must run before
    # ``collapse_duplicate_hits``.
    if getattr(settings, "rank_results", False) and merged_hits:
        deduplicated_hits = rank_and_dedup_results(
            merged_hits, query, options.max_total_results
        )
    else:
        deduplicated_hits = collapse_duplicate_hits(merged_hits)

    deduplicated_hits = deduplicated_hits[: options.max_total_results]
    for idx, hit in enumerate(deduplicated_hits, start=1):
        hit.rank = idx

    report = SearchReport(
        query=query,
        results=deduplicated_hits,
        related_searches=_unique_strings(related_searches),
        suggestions=_unique_strings(suggestions),
        answer_box=answer_box,
        timing_ms=round((time.monotonic() - started_at) * 1000, 1),
        providers=provider_reports,
        errors=errors,
    )
    if cache is not None:
        cache.set(cache_key, report.model_dump(mode="json"))
    return report
