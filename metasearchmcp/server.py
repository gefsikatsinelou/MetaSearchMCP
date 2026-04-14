from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from metasearchmcp import __version__
from metasearchmcp.api.routes import router
from metasearchmcp.config import get_settings

app = FastAPI(
    title="MetaSearchMCP",
    description=(
        "MCP-first metasearch backend for AI agents and structured search workflows. "
        "Aggregates multiple providers into a stable JSON schema."
    ),
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "metasearchmcp.server:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=False,
    )


if __name__ == "__main__":
    run()
