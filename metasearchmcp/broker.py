"""MCP server exposing MetaSearchMCP tools over stdio."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server
from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.models import InitializationOptions

from metasearchmcp.catalog import (
    build_provider_catalog,
    pick_named_providers,
    pick_providers_by_tags,
    pick_tagged_providers,
)
from metasearchmcp.contracts import SearchOptions
from metasearchmcp.orchestrator import run_search_plan

server = Server("MetaSearchMCP")
_catalog = build_provider_catalog()

_TOOLS = [
    types.Tool(
        name="search_web",
        description=(
            "Aggregate structured web search results from all enabled providers."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "providers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Explicit provider list; empty = all enabled.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional provider tags used to narrow the provider set.",
                },
                "num_results": {
                    "type": "integer",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50,
                },
                "max_total_results": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Cap the final merged result set returned to the agent.",
                },
                "language": {"type": "string", "default": "en"},
                "country": {"type": "string", "default": "us"},
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="search_google",
        description="Search Google through configured hosted providers.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "provider": {
                    "type": "string",
                    "enum": ["google_serpbase", "google_serper", ""],
                    "default": "",
                },
                "num_results": {"type": "integer", "default": 10},
                "max_total_results": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="search_academic",
        description="Search academic and reference sources for research workflows.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "num_results": {"type": "integer", "default": 10},
                "max_total_results": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="search_github",
        description="Search GitHub repositories with structured metadata.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "num_results": {"type": "integer", "default": 10},
                "max_total_results": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="compare_engines",
        description="Compare providers side by side for the same query.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "providers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Providers to compare. Empty = all enabled.",
                },
                "num_results": {"type": "integer", "default": 5},
                "max_total_results": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return _TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    try:
        result = await dispatch_tool(name, arguments)
        return [
            types.TextContent(
                type="text",
                text=json.dumps(result, indent=2, ensure_ascii=False),
            )
        ]
    except Exception as exc:
        return [
            types.TextContent(
                type="text",
                text=json.dumps({"error": str(exc), "tool": name}),
            )
        ]


async def dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    query = arguments["query"]
    num_results = int(arguments.get("num_results", 10))
    max_total_results = int(arguments.get("max_total_results", 20))
    options = SearchOptions(
        num_results=num_results,
        max_total_results=max_total_results,
    )

    if name == "search_web":
        options = SearchOptions(
            num_results=num_results,
            max_total_results=max_total_results,
            language=arguments.get("language", "en"),
            country=arguments.get("country", "us"),
        )
        selected = pick_providers_by_tags(_catalog, arguments.get("tags") or [])
        selected = pick_named_providers(selected, arguments.get("providers") or [])
        if not selected:
            return {"error": "No providers available for the requested filters."}
        return (
            await run_search_plan(query, list(selected.values()), options)
        ).model_dump()

    if name == "search_google":
        selected = pick_tagged_providers(_catalog, "google")
        provider_name = arguments.get("provider", "")
        if provider_name:
            selected = {
                name: provider
                for name, provider in selected.items()
                if name == provider_name
            }
        if not selected:
            return {
                "error": "No Google provider available. Set SERPBASE_API_KEY or SERPER_API_KEY."
            }
        return (
            await run_search_plan(query, list(selected.values()), options)
        ).model_dump()

    if name == "search_academic":
        selected = pick_tagged_providers(_catalog, "academic")
        if not selected:
            return {"error": "No academic providers available."}
        return (
            await run_search_plan(query, list(selected.values()), options)
        ).model_dump()

    if name == "search_github":
        selected = pick_named_providers(_catalog, ["github"])
        if not selected:
            return {"error": "GitHub provider not available."}
        return (
            await run_search_plan(query, list(selected.values()), options)
        ).model_dump()

    if name == "compare_engines":
        selected = pick_named_providers(_catalog, arguments.get("providers") or [])
        if not selected:
            return {"error": "No providers available for comparison."}

        jobs = [
            run_search_plan(
                query,
                [provider],
                SearchOptions(
                    num_results=num_results,
                    max_total_results=max_total_results,
                ),
            )
            for provider in selected.values()
        ]
        responses = await asyncio.gather(*jobs, return_exceptions=True)
        comparison: dict[str, Any] = {"query": query, "engines": {}}
        for provider_name, response in zip(selected.keys(), responses):
            if isinstance(response, Exception):
                comparison["engines"][provider_name] = {"error": str(response)}
            else:
                comparison["engines"][provider_name] = {
                    "results": [result.model_dump() for result in response.results],
                    "timing_ms": response.timing_ms,
                }
        return comparison

    return {"error": f"Unknown tool: {name}"}


async def _main() -> None:
    options = InitializationOptions(
        server_name="MetaSearchMCP",
        server_version="0.1.0",
        capabilities=server.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)


def run() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    run()
