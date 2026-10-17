"""Opt-in, anonymous Parallel Search MCP provider."""

from __future__ import annotations

import asyncio
from typing import ClassVar

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_MCP_URL = "https://search.parallel.ai/mcp"


class _ParallelHit(BaseModel):
    url: str
    title: str | None = None
    publish_date: str | None = None
    excerpts: list[str]


class _ParallelResponse(BaseModel):
    results: list[_ParallelHit]


class ParallelProvider(BaseProvider):
    """Free Fast-mode web search, enabled with ``PARALLEL_ENABLED=true``.

    The anonymous MCP endpoint does not expose language, country or safe-search
    controls. Result counts are capped locally; no API key is sent.
    """

    name = "parallel"
    description = "Parallel Fast web search over MCP, no API key required (opt-in)."
    tags: ClassVar[list[str]] = ["web"]

    def is_available(self) -> bool:
        """Keep the provider out of the default catalog until explicitly enabled."""
        return get_settings().parallel_enabled

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Call Parallel through Streamable HTTP within the provider timeout."""
        async with (
            asyncio.timeout(self._timeout),
            self._client() as client,
            streamable_http_client(_MCP_URL, http_client=client) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            response = await session.call_tool(
                "web_search", {"objective": query, "search_queries": [query]}
            )
        text = "\n".join(
            block.text for block in response.content if block.type == "text"
        )
        if response.isError:
            raise RuntimeError(f"Parallel search failed: {text}")
        if response.structuredContent is not None:
            data = _ParallelResponse.model_validate(response.structuredContent)
        else:
            data = _ParallelResponse.model_validate_json(text)

        limit = min(params.num_results, self._max_results)
        return ProviderResult(
            results=[
                SearchResult(
                    title=hit.title or hit.url,
                    url=hit.url,
                    snippet="\n\n".join(hit.excerpts)[:MAX_SNIPPET_LENGTH],
                    provider=self.name,
                    rank=rank,
                    published_date=self._iso_date_prefix(hit.publish_date),
                    extra={"excerpts": hit.excerpts},
                )
                for rank, hit in enumerate(data.results[:limit], start=1)
            ]
        )
