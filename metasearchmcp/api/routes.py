from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from metasearchmcp.catalog import (
    build_provider_catalog,
    pick_named_providers,
    pick_tagged_providers,
)
from metasearchmcp.contracts import (
    GoogleSearchEnvelope,
    SearchEnvelope,
    SearchReport,
)
from metasearchmcp.orchestrator import run_search_plan

router = APIRouter()

# Module-level provider catalog, built once at import time.
_catalog = build_provider_catalog()


def _get_registry():
    return _catalog


@router.post(
    "/search",
    response_model=SearchReport,
    summary="Aggregate search across all enabled providers",
)
async def search(
    req: SearchEnvelope,
    registry=Depends(_get_registry),
) -> SearchReport:
    providers_map = pick_named_providers(registry, req.providers)
    if not providers_map:
        raise HTTPException(
            status_code=503,
            detail="No providers available. Check configuration and API keys.",
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
        selected = google_providers

    if not selected:
        raise HTTPException(
            status_code=503,
            detail=(
                "No Google provider available. "
                "Set SERPBASE_API_KEY or SERPER_API_KEY in your environment."
            ),
        )

    return await run_search_plan(req.query, list(selected.values()), req.params)


@router.get("/health", summary="Health check")
async def health() -> dict:
    return {"status": "ok"}


@router.get(
    "/providers", summary="List all configured providers and their availability"
)
async def providers(registry=Depends(_get_registry)) -> dict:
    return {
        "available": [{"name": p.name, "tags": p.tags} for p in registry.values()],
        "count": len(registry),
    }
