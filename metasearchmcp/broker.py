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
    pick_first_provider,
    pick_named_providers,
    pick_providers_by_tags,
    pick_tagged_providers,
)
from metasearchmcp.config import (
    GOOGLE_PROVIDER_UNAVAIL_TMPL,
    NO_GOOGLE_PROVIDER_MSG,
    NO_PROVIDERS_MSG,
    SERPBASE_DASHBOARD_URL,
    USER_CONFIG_FILE,
    get_settings,
)
from metasearchmcp.contracts import (
    DEFAULT_MAX_TOTAL_RESULTS,
    DEFAULT_NUM_RESULTS,
    MAX_NUM_RESULTS,
    MAX_TOTAL_RESULTS,
    SearchOptions,
)
from metasearchmcp.orchestrator import run_search_plan

if TYPE_CHECKING:
    from metasearchmcp.providers.base import BaseProvider

server: Server = Server("MetaSearchMCP")
_catalog: dict[str, BaseProvider] = build_provider_catalog()

# Tool name constants -- single source of truth for both MCP definitions
# and the dispatch handler map, preventing name drift between the two.
_TOOL_SEARCH_WEB = "search_web"
_TOOL_SEARCH_GOOGLE = "search_google"
_TOOL_SEARCH_ACADEMIC = "search_academic"
_TOOL_SEARCH_GITHUB = "search_github"
_TOOL_COMPARE_ENGINES = "compare_engines"
_TOOL_SEARCH_FINANCE = "search_finance"
_TOOL_SEARCH_CODE = "search_code"
_TOOL_SEARCH_NEWS = "search_news"
_TOOL_SEARCH_SOCIAL = "search_social"
_TOOL_SEARCH_IMAGES = "search_images"
_TOOL_SEARCH_VIDEOS = "search_videos"
_TOOL_SEARCH_BIO = "search_bio"
_TOOL_LIST_PROVIDERS = "list_providers"
_TOOL_PROVIDER_HEALTH = "provider_health"

# Shared result-count schema properties reused across tool definitions.
_RESULT_COUNT_PROPERTIES: dict[str, Any] = {
    "num_results": {
        "type": "integer",
        "default": DEFAULT_NUM_RESULTS,
        "minimum": 1,
        "maximum": MAX_NUM_RESULTS,
        "description": "Number of results per provider.",
    },
    "max_total_results": {
        "type": "integer",
        "default": DEFAULT_MAX_TOTAL_RESULTS,
        "minimum": 1,
        "maximum": MAX_TOTAL_RESULTS,
        "description": ("Cap the final merged result set returned to the agent."),
    },
}

# Shared safe-search property reused across search tool definitions.
_SAFE_SEARCH_PROPERTY: dict[str, Any] = {
    "type": "boolean",
    "default": True,
    "description": "Enable safe search filtering.",
}

_TOOLS: list[types.Tool] = [
    types.Tool(
        name=_TOOL_SEARCH_WEB,
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
                "safe_search": _SAFE_SEARCH_PROPERTY,
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name=_TOOL_SEARCH_GOOGLE,
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
                "safe_search": _SAFE_SEARCH_PROPERTY,
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name=_TOOL_SEARCH_ACADEMIC,
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
        name=_TOOL_SEARCH_GITHUB,
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
        name=_TOOL_COMPARE_ENGINES,
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
                **_RESULT_COUNT_PROPERTIES,
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name=_TOOL_SEARCH_FINANCE,
        description=(
            "Search stock tickers, company names, and financial instruments "
            "across finance providers (Yahoo Finance, Alpha Vantage, Finnhub, "
            "SEC EDGAR filings)."
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
        name=_TOOL_SEARCH_CODE,
        description=(
            "Search code repositories, packages, and developer resources across "
            "GitHub, GitLab, npm, PyPI, crates.io, pkg.go.dev, MetaCPAN, lib.rs, "
            "Maven Central, RubyGems, Docker Hub, Stack Overflow, and Hacker News."
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
    types.Tool(
        name=_TOOL_SEARCH_NEWS,
        description=(
            "Search recent news headlines and articles across news providers "
            "(Google News, Hacker News, Lobsters, Lemmy, Reddit)."
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
    types.Tool(
        name=_TOOL_SEARCH_SOCIAL,
        description=(
            "Search social media posts and community discussions across "
            "Bluesky, Mastodon, Lemmy, and Lobsters."
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
    types.Tool(
        name=_TOOL_SEARCH_IMAGES,
        description=(
            "Search images across image providers (Openverse, Wikimedia "
            "Commons, Flickr, Unsplash, NASA Image Library)."
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
    types.Tool(
        name=_TOOL_SEARCH_VIDEOS,
        description=("Search videos and streaming media across PeerTube instances."),
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
        name=_TOOL_SEARCH_BIO,
        description=(
            "Search biomedical and life-science databases: proteins "
            "(UniProt), clinical trials (ClinicalTrials.gov), and "
            "literature (PubMed, Europe PMC)."
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
    types.Tool(
        name=_TOOL_LIST_PROVIDERS,
        description=(
            "List all available search providers with their names, descriptions, "
            "and tags. Use this to discover what search backends are available "
            "before issuing queries."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "tag": {
                    "type": "string",
                    "description": (
                        "Optional tag to filter providers "
                        "(e.g. 'web', 'academic', 'code', 'finance', 'news', 'social')."
                    ),
                },
            },
        },
    ),
    types.Tool(
        name=_TOOL_PROVIDER_HEALTH,
        description=(
            "Report availability/health of search providers. For each provider, "
            "returns whether it is enabled and configured to run (e.g. missing "
            "API keys make a provider unavailable). Optionally filter by tag."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "tag": {
                    "type": "string",
                    "description": (
                        "Optional tag to filter providers "
                        "(e.g. 'web', 'academic', 'code', 'finance', 'news', 'social')."
                    ),
                },
            },
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
        return {
            "error": NO_PROVIDERS_MSG,
        }
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
        if provider_name not in selected:
            return {
                "error": GOOGLE_PROVIDER_UNAVAIL_TMPL.format(
                    name=provider_name,
                    available=list(selected.keys()),
                ),
            }
        selected = {provider_name: selected[provider_name]}
    else:
        selected = pick_first_provider(selected)
    if not selected:
        return {
            "error": NO_GOOGLE_PROVIDER_MSG,
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
        return {
            "error": (
                "No providers available for comparison. "
                "Check configuration and API keys."
            ),
        }
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


async def _dispatch_list_providers(
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Return a summary of all available providers, optionally filtered by tag."""
    tag_filter = (arguments.get("tag") or "").strip().lower()
    providers_info: list[dict[str, Any]] = []
    for _pname, provider in sorted(_catalog.items()):
        if tag_filter and tag_filter not in {t.lower() for t in provider.tags}:
            continue
        providers_info.append(
            {
                "name": provider.name,
                "description": provider.description,
                "tags": sorted(provider.tags),
            },
        )
    return {
        "providers": providers_info,
        "count": len(providers_info),
        "tag_filter": tag_filter or None,
    }


async def _dispatch_provider_health(
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Report availability of each provider, optionally filtered by tag."""
    tag_filter = (arguments.get("tag") or "").strip().lower()
    provider_statuses: list[dict[str, Any]] = []
    for _pname, provider in sorted(_catalog.items()):
        if tag_filter and tag_filter not in {t.lower() for t in provider.tags}:
            continue
        available = provider.is_available()
        provider_statuses.append(
            {
                "name": provider.name,
                "available": available,
                "status": "ok" if available else "unavailable",
                "description": provider.description,
                "tags": sorted(provider.tags),
            },
        )
    available_count = sum(1 for s in provider_statuses if s["available"])
    return {
        "providers": provider_statuses,
        "count": len(provider_statuses),
        "available_count": available_count,
        "unavailable_count": len(provider_statuses) - available_count,
        "tag_filter": tag_filter or None,
    }


async def dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Route a tool call to the appropriate search handler."""
    # list_providers and provider_health do not require a query.
    if name == _TOOL_LIST_PROVIDERS:
        return await _dispatch_list_providers(arguments)
    if name == _TOOL_PROVIDER_HEALTH:
        return await _dispatch_provider_health(arguments)

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
        _TOOL_SEARCH_WEB: lambda: _dispatch_search_web(query, arguments, options),
        _TOOL_SEARCH_GOOGLE: lambda: _dispatch_search_google(query, arguments, options),
        _TOOL_SEARCH_ACADEMIC: lambda: _run_tagged_search(
            query,
            options,
            "academic",
            "No academic providers available.",
        ),
        _TOOL_SEARCH_GITHUB: lambda: _run_named_search(
            query,
            options,
            ["github"],
            "GitHub provider not available.",
        ),
        _TOOL_COMPARE_ENGINES: lambda: _dispatch_compare_engines(
            query,
            arguments,
            options,
        ),
        _TOOL_SEARCH_FINANCE: lambda: _run_tagged_search(
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
        _TOOL_SEARCH_CODE: lambda: _run_tagged_search(
            query,
            options,
            "code",
            "No code/developer providers available.",
        ),
        _TOOL_SEARCH_NEWS: lambda: _run_tagged_search(
            query,
            options,
            "news",
            "No news providers available.",
        ),
        _TOOL_SEARCH_SOCIAL: lambda: _run_tagged_search(
            query,
            options,
            "social",
            "No social media providers available.",
        ),
        _TOOL_SEARCH_IMAGES: lambda: _run_tagged_search(
            query,
            options,
            "image",
            "No image providers available.",
        ),
        _TOOL_SEARCH_VIDEOS: lambda: _run_tagged_search(
            query,
            options,
            "video",
            "No video providers available.",
        ),
        _TOOL_SEARCH_BIO: lambda: _run_tagged_search(
            query,
            options,
            "bio",
            "No biomedical/life-science providers available.",
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
            "  Set ALLOW_UNSTABLE_PROVIDERS=true for direct Google,\n"
            "  set SERPBASE_API_KEY (run 'metasearchmcp-setup') or SERPER_API_KEY,\n"
            f"  SerpBase key dashboard: {SERPBASE_DASHBOARD_URL}\n"
            f"  Config file: {USER_CONFIG_FILE}",
            file=sys.stderr,
        )
    asyncio.run(_main())


if __name__ == "__main__":
    run()
