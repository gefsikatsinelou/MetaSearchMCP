from __future__ import annotations

import asyncio
import time
from typing import Sequence

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import (
    ProviderPayload,
    ProviderReport,
    SearchOptions,
    SearchReport,
)
from metasearchmcp.merge import collapse_duplicate_hits
from metasearchmcp.providers.base import BaseProvider


async def execute_provider_search(
    provider: BaseProvider,
    query: str,
    options: SearchOptions,
    timeout: float,
) -> tuple[str, ProviderPayload | None, float, str | None]:
    start = time.monotonic()
    try:
        payload = await asyncio.wait_for(
            provider.search(query, options), timeout=timeout
        )
        latency_ms = (time.monotonic() - start) * 1000
        return provider.name, payload, latency_ms, None
    except asyncio.TimeoutError:
        latency_ms = (time.monotonic() - start) * 1000
        return provider.name, None, latency_ms, f"timeout after {timeout}s"
    except Exception as exc:
        latency_ms = (time.monotonic() - start) * 1000
        return provider.name, None, latency_ms, str(exc)


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique


async def run_search_plan(
    query: str,
    providers: Sequence[BaseProvider],
    options: SearchOptions | None = None,
) -> SearchReport:
    if options is None:
        options = SearchOptions()

    settings = get_settings()
    started_at = time.monotonic()
    jobs = [
        execute_provider_search(provider, query, options, settings.default_timeout)
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
                )
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
            )
        )

    deduplicated_hits = collapse_duplicate_hits(merged_hits)
    deduplicated_hits = deduplicated_hits[: options.max_total_results]
    for index, hit in enumerate(deduplicated_hits, start=1):
        deduplicated_hits[index - 1] = hit.model_copy(update={"rank": index})

    return SearchReport(
        query=query,
        results=deduplicated_hits,
        related_searches=_unique_strings(related_searches),
        suggestions=_unique_strings(suggestions),
        answer_box=answer_box,
        timing_ms=round((time.monotonic() - started_at) * 1000, 1),
        providers=provider_reports,
        errors=errors,
    )
