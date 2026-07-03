"""MCP server exposing MetaSearchMCP tools over stdio."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import TYPE_CHECKING, Any

import mcp.server.stdio
from mcp import types
from mcp.server import Server
from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.models import InitializationOptions

from metasearchmcp import __version__
from metasearchmcp.catalog import (
    build_provider_catalog,
    pick_named_providers,
    pick_providers_by_tags,
    pick_tagged_providers,
)
from metasearchmcp.config import USER_CONFIG_FILE, get_settings
from metasearchmcp.contracts import SearchOptions
from metasearchmcp.orchestrator import run_search_plan

if TYPE_CHECKING:
    from metasearchmcp.providers.base import BaseProvider

server: Server = Server("MetaSearchMCP")
_catalog: dict[str, BaseProvider] = build_provider_catalog()

# Shared result-count schema properties reused across tool definitions.
_RESULT_COUNT_PROPERTIES: dict[str, Any] = {
    "num_results": {
        "type": "integer",
        "default": 10,
        "minimum": 1,
        "maximum": 50,
        "description": "Number of results per provider.",
    },
    "max_total_results": {
        "type": "integer",
        "default": 20,
        "minimum": 1,
        "maximum": 100,
        "description": ("Cap the final merged result set returned to the agent."),
    },
}

_TOOLS: list[types.Tool] = [
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
                    "description": (
                        "Optional provider tags used to narrow the provider set."
                    ),
                },
                "tag_match": {
                    "type": "string",
                    "enum": ["any", "all"],
                    "default": "any",
                    "description": (
                        "Match providers with any requested tag or require all tags."
                    ),
                },
                **_RESULT_COUNT_PROPERTIES,
                "language": {"type": "string", "default": "en"},
                "country": {"type": "string", "default": "us"},
                "safe_search": {
                    "type": "boolean",
                    "default": True,
                    "description": "Enable safe search filtering.",
                },
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
                    "enum": ["google", "google_serpbase", "google_serper", ""],
                    "default": "",
                },
                **_RESULT_COUNT_PROPERTIES,
                "safe_search": {
                    "type": "boolean",
                    "default": True,
                    "description": "Enable safe search filtering.",
                },
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
                **_RESULT_COUNT_PROPERTIES,
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
                **_RESULT_COUNT_PROPERTIES,
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
                "num_results": {
                    "type": "integer",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Number of results per provider.",
                },
                "max_total_results": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": (
                        "Cap the final merged result set returned to the agent."
                    ),
                },
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="search_finance",
        description=(
            "Search stock tickers, company names, and financial instruments "
            "across finance providers (Yahoo Finance, Alpha Vantage, Finnhub)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Ticker symbol or company name, e.g. 'AAPL' or 'Tesla'"
                    ),
                },
                **_RESULT_COUNT_PROPERTIES,
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="search_code",
        description=(
            "Search code repositories, packages, and developer resources across "
            "GitHub, GitLab, npm, PyPI, crates.io, pkg.go.dev, MetaCPAN, lib.rs, "
            "RubyGems, Docker Hub, Stack Overflow, and Hacker News."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                **_RESULT_COUNT_PROPERTIES,
            },
            "required": ["query"],
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """Return the list of available MCP tools."""
    return _TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    """Execute an MCP tool by name with the given arguments."""
    try:
        result = await dispatch_tool(name, arguments)
        return [
            types.TextContent(
                type="text",
                text=json.dumps(result, indent=2, ensure_ascii=False),
            ),
        ]
    except Exception as exc:
        return [
            types.TextContent(
                type="text",
                text=json.dumps(
                    {"error": str(exc) or type(exc).__name__, "tool": name},
                    indent=2,
                    ensure_ascii=False,
                ),
            ),
        ]


async def _run_tagged_search(
    query: str,
    options: SearchOptions,
    tag: str,
    error_message: str,
) -> dict[str, Any]:
    """Execute a search against providers that carry *tag* and return the report."""
    selected = pick_tagged_providers(_catalog, tag)
    if not selected:
        return {"error": error_message}
    return (await run_search_plan(query, list(selected.values()), options)).model_dump()


async def _run_named_search(
    query: str,
    options: SearchOptions,
    names: list[str],
    error_message: str,
) -> dict[str, Any]:
    """Execute a search against explicitly named providers and return the report."""
    selected = pick_named_providers(_catalog, names)
    if not selected:
        return {"error": error_message}
    return (await run_search_plan(query, list(selected.values()), options)).model_dump()


async def _dispatch_search_web(
    query: str,
    arguments: dict[str, Any],
    base: SearchOptions,
) -> dict[str, Any]:
    """Handle the search_web tool dispatch."""
    options = SearchOptions(
        num_results=base.num_results,
        max_total_results=base.max_total_results,
        language=arguments.get("language", "en"),
        country=arguments.get("country", "us"),
        safe_search=arguments.get("safe_search", True),
    )
    selected = pick_providers_by_tags(
        _catalog,
        arguments.get("tags") or [],
        match=arguments.get("tag_match", "any"),
    )
    selected = pick_named_providers(selected, arguments.get("providers") or [])
    if not selected:
        return {"error": "No providers available for the requested filters."}
    return (await run_search_plan(query, list(selected.values()), options)).model_dump()


async def _dispatch_search_google(
    query: str,
    arguments: dict[str, Any],
    base: SearchOptions,
) -> dict[str, Any]:
    """Handle the search_google tool dispatch."""
    options = SearchOptions(
        num_results=base.num_results,
        max_total_results=base.max_total_results,
        safe_search=arguments.get("safe_search", True),
    )
    selected = pick_tagged_providers(_catalog, "google")
    provider_name = arguments.get("provider", "")
    if provider_name:
        selected = {
            name: provider
            for name, provider in selected.items()
            if name == provider_name
        }
    else:
        first_available = next(iter(selected.items()), None)
        selected = {first_available[0]: first_available[1]} if first_available else {}
    if not selected:
        return {
            "error": (
                "No Google provider available. "
                "Enable ALLOW_UNSTABLE_PROVIDERS=true for direct Google, "
                "or set SERPBASE_API_KEY / SERPER_API_KEY."
            ),
        }
    return (await run_search_plan(query, list(selected.values()), options)).model_dump()


async def _dispatch_compare_engines(
    query: str,
    arguments: dict[str, Any],
    options: SearchOptions,
) -> dict[str, Any]:
    """Handle the compare_engines tool dispatch."""
    selected = pick_named_providers(_catalog, arguments.get("providers") or [])
    if not selected:
        selected = _catalog
    if not selected:
        return {"error": "No providers available for comparison."}
    jobs = [
        run_search_plan(
            query,
            [provider],
            SearchOptions(
                num_results=options.num_results,
                max_total_results=options.max_total_results,
            ),
        )
        for provider in selected.values()
    ]
    responses = await asyncio.gather(*jobs, return_exceptions=True)
    comparison: dict[str, Any] = {"query": query, "engines": {}}
    for provider_name, response in zip(selected.keys(), responses, strict=True):
        if isinstance(response, Exception):
            comparison["engines"][provider_name] = {
                "error": str(response) or type(response).__name__,
            }
        else:
            comparison["engines"][provider_name] = {
                "results": [result.model_dump() for result in response.results],
                "timing_ms": response.timing_ms,
            }
    return comparison


async def dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Route a tool call to the appropriate search handler."""
    query = arguments["query"]
    # Build SearchOptions, relying on Pydantic defaults when values are
    # omitted or explicitly None (e.g. `"num_results": null` from JSON).
    kwargs: dict[str, Any] = {}
    num = arguments.get("num_results")
    if num is not None:
        kwargs["num_results"] = int(num)
    max_r = arguments.get("max_total_results")
    if max_r is not None:
        kwargs["max_total_results"] = int(max_r)
    options = SearchOptions(**kwargs)

    handlers: dict[str, Any] = {
        "search_web": lambda: _dispatch_search_web(query, arguments, options),
        "search_google": lambda: _dispatch_search_google(query, arguments, options),
        "search_academic": lambda: _run_tagged_search(
            query,
            options,
            "academic",
            "No academic providers available.",
        ),
        "search_github": lambda: _run_named_search(
            query,
            options,
            ["github"],
            "GitHub provider not available.",
        ),
        "compare_engines": lambda: _dispatch_compare_engines(query, arguments, options),
        "search_finance": lambda: _run_tagged_search(
            query,
            options,
            "finance",
            (
                "No finance providers available. "
                "yahoo_finance is enabled by default; "
                "set ALPHA_VANTAGE_API_KEY or FINNHUB_API_KEY "
                "for additional providers."
            ),
        ),
        "search_code": lambda: _run_tagged_search(
            query,
            options,
            "code",
            "No code/developer providers available.",
        ),
    }

    handler = handlers.get(name)
    if handler is None:
        return {"error": f"Unknown tool: {name}"}
    return await handler()


async def _main() -> None:
    """Start the MCP server loop over stdio with initialization options."""
    options = InitializationOptions(
        server_name="MetaSearchMCP",
        server_version=__version__,
        capabilities=server.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)


def run() -> None:
    """Start the MCP server over stdio."""
    settings = get_settings()
    if not (
        settings.allow_unstable_providers
        or settings.serpbase_api_key
        or settings.serper_api_key
    ):
        print(
            "[MetaSearchMCP] No Google provider configured.\n"
            "  Set ALLOW_UNSTABLE_PROVIDERS=true for direct Google, "
            "or run 'metasearchmcp-setup' for SerpBase.\n"
            f"  SerpBase key dashboard: https://serpbase.dev/dashboard/api-keys\n"
            f"  Config file: {USER_CONFIG_FILE}",
            file=sys.stderr,
        )
    asyncio.run(_main())


if __name__ == "__main__":
    run()
