# MetaSearchMCP

Open-source metasearch backend for MCP, AI agents, and LLM workflows.

MetaSearchMCP aggregates results from multiple search providers, normalizes them into a stable JSON schema, and exposes both an HTTP API and an MCP server for agent tooling.

## Positioning

- MCP-first metasearch backend
- Structured search API for AI pipelines
- Multi-provider search orchestration with deduplication and fallback
- Python FastAPI alternative to browser-first metasearch projects

## Why It Exists

Most search aggregators are designed around browser UX: HTML pages, pagination, and interactive result cards. Agents and LLM workflows need a different contract: predictable JSON, stable field names, partial-failure tolerance, and provider-level execution metadata.

MetaSearchMCP is built for that machine-consumable workflow. The design is centered on search orchestration, normalized contracts, and MCP integration.

## Core Features

- Concurrent multi-provider aggregation
- Unified result schema for web, academic, developer, and knowledge sources
- Provider-level timeout isolation and partial-failure handling
- Result deduplication across engines
- Provider selection by explicit names or semantic tags such as `web`, `academic`, `code`, and `google`
- Final result caps for agent-friendly payload sizing
- HTTP API with OpenAPI docs
- MCP server over stdio for Claude Desktop, Cline, Continue, and similar clients
- Configurable provider allowlist via environment variables

## Google Support

Google support now includes a direct scraper provider implemented inside this project.

The direct Google implementation uses browser-like requests, consent cookie handling, locale-aware query parameters, and resilient HTML result parsing. It is implemented locally in this repository.

Currently supported Google providers:

| Provider | Env var | Notes |
|---|---|---|
| Direct Google | `ALLOW_UNSTABLE_PROVIDERS=true` | Primary path; HTML scraping, best effort, may be blocked from datacenter IPs |
| [serpbase.dev](https://serpbase.dev) | `SERPBASE_API_KEY` | Pay-per-use; typically cheaper for low-volume usage |
| [serper.dev](https://serper.dev) | `SERPER_API_KEY` | Includes a free tier, then pay-per-use |

Provider priority for `/search/google` is now `google` first, then `google_serpbase`, then `google_serper`.

## Supported Providers

### Google

| Provider | Name | Method |
|---|---|---|
| Direct Google | `google` | HTML scraping with browser-like request handling |
| SerpBase | `google_serpbase` | Hosted Google SERP API |
| Serper | `google_serper` | Hosted Google SERP API |

### Web Search

| Provider | Name | Method |
|---|---|---|
| DuckDuckGo | `duckduckgo` | HTML scraping |
| Bing | `bing` | RSS feed |
| Yahoo | `yahoo` | HTML scraping, best effort |
| Brave | `brave` | Official Search API |
| Mwmbl | `mwmbl` | Public JSON API |
| Ecosia | `ecosia` | HTML scraping |
| Mojeek | `mojeek` | HTML scraping |
| Startpage | `startpage` | HTML scraping, best effort |
| Qwant | `qwant` | Internal JSON API, best effort |
| Yandex | `yandex` | HTML scraping, best effort |
| Baidu | `baidu` | JSON endpoint, best effort |

### Knowledge And Reference

| Provider | Name | Method |
|---|---|---|
| Wikipedia | `wikipedia` | MediaWiki API |
| Wikidata | `wikidata` | Wikidata API |
| Internet Archive | `internet_archive` | Advanced Search API |
| Open Library | `openlibrary` | Open Library search API |

### Developer Sources

| Provider | Name | Method |
|---|---|---|
| GitHub | `github` | GitHub REST API |
| GitLab | `gitlab` | GitLab REST API |
| Stack Overflow | `stackoverflow` | Stack Exchange API |
| Hacker News | `hackernews` | Algolia HN API |
| Reddit | `reddit` | Reddit API |
| npm | `npm` | npm registry API |
| PyPI | `pypi` | HTML scraping |
| RubyGems | `rubygems` | RubyGems search API |
| crates.io | `crates` | crates.io API |
| lib.rs | `lib_rs` | HTML scraping |
| Docker Hub | `dockerhub` | Docker Hub search API |
| pkg.go.dev | `pkg_go_dev` | HTML scraping |
| MetaCPAN | `metacpan` | MetaCPAN REST API |

### Academic Sources

| Provider | Name | Method |
|---|---|---|
| arXiv | `arxiv` | Atom API |
| PubMed | `pubmed` | NCBI E-utilities |
| Semantic Scholar | `semanticscholar` | Graph API |
| CrossRef | `crossref` | REST API |

### Finance Sources

| Provider | Name | Key Required | Free Tier |
|---|---|---|---|
| Yahoo Finance | `yahoo_finance` | No | Unofficial endpoint, no key needed |
| Alpha Vantage | `alpha_vantage` | `ALPHA_VANTAGE_API_KEY` | 25 req/day — [get key](https://www.alphavantage.co/support/#api-key) |
| Finnhub | `finnhub` | `FINNHUB_API_KEY` | 60 req/min — [get key](https://finnhub.io/register) |

## Installation

One-command local install:

```bash
python scripts/install.py
```

Install, run tests, and start the HTTP API:

```bash
python scripts/install.py --dev --test --run
```

Deploy with Docker Compose:

```bash
python scripts/install.py --mode docker
```

The installer creates `.env` from `.env.example` when `.env` does not already exist. Existing `.env` files are kept unless `--force-env` is passed.

Manual install:

```bash
git clone https://github.com/gefsikatsinelou/MetaSearchMCP
cd MetaSearchMCP
pip install -e ".[dev]"
```

Or with `uv`:

```bash
uv pip install -e ".[dev]"
```

## Configuration

Copy `.env.example` to `.env` and configure any providers you want to enable.

```bash
cp .env.example .env
```

Key settings:

```env
HOST=0.0.0.0
PORT=8000
DEFAULT_TIMEOUT=10
AGGREGATOR_TIMEOUT=15

SERPBASE_API_KEY=
SERPER_API_KEY=
BRAVE_API_KEY=
GITHUB_TOKEN=
STACKEXCHANGE_API_KEY=
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
NCBI_API_KEY=
SEMANTIC_SCHOLAR_API_KEY=
ALPHA_VANTAGE_API_KEY=
FINNHUB_API_KEY=

ENABLED_PROVIDERS=
ALLOW_UNSTABLE_PROVIDERS=false
MAX_RESULTS_PER_PROVIDER=10
```

## Running

### HTTP API

```bash
python -m metasearchmcp.server
# or
metasearchmcp
```

The API starts on `http://localhost:8000`.

### MCP Server

```bash
python -m metasearchmcp.broker
# or
metasearchmcp-mcp
```

The MCP server communicates over stdio.

### Docker

```bash
docker build -t metasearchmcp .
docker run --rm -p 8000:8000 --env-file .env metasearchmcp
```

Or with Compose:

```bash
docker compose up --build
```

## HTTP API

### `POST /search`

Aggregate across all enabled providers or a selected provider subset.

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "rust async runtime",
    "providers": ["duckduckgo", "wikipedia"],
    "params": {"num_results": 5, "max_total_results": 8, "language": "en"}
  }'
```

You can also narrow providers by tags:

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "transformer attention",
    "tags": ["academic", "knowledge"],
    "params": {"num_results": 5, "max_total_results": 6}
  }'
```

When multiple tags are provided, the default behavior is `tag_match="any"`.
Set `tag_match` to `"all"` when you want providers that satisfy every requested tag:

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "npm cli argument parser",
    "tags": ["code", "packages"],
    "tag_match": "all",
    "params": {"num_results": 5, "max_total_results": 6}
  }'
```

`num_results` controls how many results each provider can contribute. `max_total_results` caps the final merged response after deduplication.

### `POST /search/google`

Search Google through the configured Google provider chain. If `ALLOW_UNSTABLE_PROVIDERS=true`, MetaSearchMCP will prefer the direct `google` provider automatically.

```bash
curl -X POST http://localhost:8000/search/google \
  -H "Content-Type: application/json" \
  -d '{"query": "site:github.com rust tokio"}'
```

To force the direct Google route explicitly:

```bash
curl -X POST http://localhost:8000/search/google \
  -H "Content-Type: application/json" \
  -d '{"query": "site:github.com rust tokio", "provider": "google"}'
```

### `GET /providers`

Return the currently available provider catalog.

The response includes provider descriptions and a tag-to-provider index for quick discovery.

You can filter the catalog by tag:

```bash
curl "http://localhost:8000/providers?tag=academic&tag=web"
```

Use `tag_match=all` to require every tag instead of the default any-match behavior:

```bash
curl "http://localhost:8000/providers?tag=code&tag=packages&tag_match=all"
```

### `GET /health`

Simple health check endpoint. Returns service status, version, provider count, and the current provider name list.

## Response Schema

Every aggregated response includes:

- `engine`
- `query`
- `results`
- `related_searches`
- `suggestions`
- `answer_box`
- `timing_ms`
- `providers`
- `errors`

Every result item includes:

- `title`
- `url`
- `snippet`
- `source`
- `rank`
- `provider`
- `published_date`
- `extra`

Example response:

```json
{
  "engine": "metasearchmcp",
  "query": "rust async runtime",
  "results": [
    {
      "title": "Tokio - An asynchronous Rust runtime",
      "url": "https://tokio.rs",
      "snippet": "Tokio is an event-driven, non-blocking I/O platform...",
      "source": "tokio.rs",
      "rank": 1,
      "provider": "duckduckgo",
      "published_date": null,
      "extra": {}
    }
  ],
  "related_searches": [],
  "suggestions": [],
  "answer_box": null,
  "timing_ms": 843.2,
  "providers": [
    {
      "name": "duckduckgo",
      "success": true,
      "result_count": 10,
      "latency_ms": 840.1,
      "error": null
    }
  ],
  "errors": []
}
```

## MCP Tools

MetaSearchMCP exposes these MCP tools:

- `search_web`
- `search_google`
- `search_academic`
- `search_github`
- `compare_engines`

`search_web` also accepts optional `tags` so agents can limit search to categories such as `web`, `academic`, `code`, or `google`. When multiple tags are present, `tag_match="all"` requires a provider to satisfy the full set.
All search tools accept `max_total_results` to keep the final payload compact.

Example Claude Desktop config:

```json
{
  "mcpServers": {
    "MetaSearchMCP": {
      "command": "metasearchmcp-mcp",
      "env": {
        "ALLOW_UNSTABLE_PROVIDERS": "true",
        "SERPBASE_API_KEY": "your_key",
        "SERPER_API_KEY": "your_key"
      }
    }
  }
}
```

## Development

```bash
pip install -e ".[dev]"
pytest
uvicorn metasearchmcp.server:app --reload
```

## Architecture

The public package is organized around these modules:

- `contracts.py`: request and response models
- `catalog.py`: provider discovery and selection
- `orchestrator.py`: concurrent search execution and response assembly
- `merge.py`: URL normalization and deduplication
- `server.py`: FastAPI entrypoint
- `broker.py`: MCP entrypoint

Legacy module names are kept as compatibility shims for earlier imports.

## Roadmap

- Caching and provider-aware query reuse
- Better scoring and ranking signals across providers
- Streaming aggregation responses
- Provider health telemetry
- More first-party API integrations where they improve reliability

## License

MIT
