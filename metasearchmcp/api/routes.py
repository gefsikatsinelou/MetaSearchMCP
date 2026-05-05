from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from metasearchmcp import __version__
from metasearchmcp.catalog import (
    build_provider_catalog,
    pick_named_providers,
    pick_providers_by_tags,
    pick_tagged_providers,
)
from metasearchmcp.contracts import (
    GoogleSearchEnvelope,
    SearchEnvelope,
    SearchReport,
)
from metasearchmcp.orchestrator import run_search_plan
from metasearchmcp.providers.base import BaseProvider

router = APIRouter()

# Module-level provider catalog, built once at import time.
_catalog = build_provider_catalog()


def _get_registry() -> dict[str, BaseProvider]:
    return _catalog


def _build_tag_groups(registry: dict) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for provider in registry.values():
        for tag in provider.tags:
            groups.setdefault(tag, []).append(provider.name)

    return {tag: sorted(names) for tag, names in sorted(groups.items())}


@router.post(
    "/search",
    response_model=SearchReport,
    summary="Aggregate search across all enabled providers",
)
async def search(
    req: SearchEnvelope,
    registry=Depends(_get_registry),
) -> SearchReport:
    providers_map = pick_providers_by_tags(registry, req.tags, match=req.tag_match)
    providers_map = pick_named_providers(providers_map, req.providers)
    if not providers_map:
        raise HTTPException(
            status_code=503,
            detail=(
                "No providers available for the requested filters. "
                "Check provider names, tags, configuration, and API keys."
            ),
        )
    return await run_search_plan(req.query, list(providers_map.values()), req.params)


@router.post(
    "/search/google",
    response_model=SearchReport,
    summary="Google search via configured provider",
)
async def search_google(
    req: GoogleSearchEnvelope,
    registry=Depends(_get_registry),
) -> SearchReport:
    google_providers = pick_tagged_providers(registry, "google")

    if req.provider:
        if req.provider not in google_providers:
            raise HTTPException(
                status_code=400,
                detail=f"Google provider '{req.provider}' is not available. "
                f"Available: {list(google_providers.keys())}",
            )
        selected = {req.provider: google_providers[req.provider]}
    else:
        first_available = next(iter(google_providers.items()), None)
        selected = {first_available[0]: first_available[1]} if first_available else {}

    if not selected:
        raise HTTPException(
            status_code=503,
            detail=(
                "No Google provider available. "
                "Enable ALLOW_UNSTABLE_PROVIDERS=true for direct Google, or set SERPBASE_API_KEY / SERPER_API_KEY."
            ),
        )

    return await run_search_plan(req.query, list(selected.values()), req.params)


@router.get("/health", summary="Health check")
async def health(registry=Depends(_get_registry)) -> dict:
    provider_names = sorted(registry.keys())
    return {
        "status": "ok",
        "version": __version__,
        "provider_count": len(registry),
        "providers": provider_names,
    }


@router.get(
    "/providers",
    summary="List all configured providers and their availability",
)
async def providers(
    tag: list[str] | None = Query(default=None),
    tag_match: Literal["any", "all"] = Query(default="any"),
    registry=Depends(_get_registry),
) -> dict:
    filtered = pick_providers_by_tags(registry, tag or [], match=tag_match)

    return {
        "available": sorted(
            [
                {"name": p.name, "tags": sorted(p.tags), "description": p.description}
                for p in filtered.values()
            ],
            key=lambda provider: provider["name"],
        ),
        "count": len(filtered),
        "tag_groups": _build_tag_groups(filtered),
        "filters": {"tags": tag or [], "tag_match": tag_match},
    }
