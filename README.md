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
| You.com | `youcom` | Official Search API |
| Mwmbl | `mwmbl` | Public JSON API |
| Marginalia | `marginalia` | Public JSON API, no key required |
| Ecosia | `ecosia` | HTML scraping |
| Mojeek | `mojeek` | HTML scraping |
| Startpage | `startpage` | HTML scraping, best effort |
| Qwant | `qwant` | Internal JSON API, best effort |
| Yandex | `yandex` | HTML scraping, best effort |
| Baidu | `baidu` | JSON endpoint, best effort |
| Seznam | `seznam` | HTML scraping (Czech web), no key required |
| Ahmia | `ahmia` | HTML scraping (Tor .onion services), no key required |

### Knowledge And Reference

| Provider | Name | Method |
|---|---|---|
| Wikipedia | `wikipedia` | MediaWiki API |
| Wikidata | `wikidata` | Wikidata API |
| Wikiquote | `wikiquote` | MediaWiki API |
| Wikisource | `wikisource` | MediaWiki API, no key required |
| Wikibooks | `wikibooks` | MediaWiki API, no key required |
| Wiktionary | `wiktionary` | MediaWiki API, no key required |
| Wikivoyage | `wikivoyage` | MediaWiki API, no key required |
| Wikiversity | `wikiversity` | MediaWiki API, no key required |
| Internet Archive | `internet_archive` | Advanced Search API |
| Open Library | `openlibrary` | Open Library search API |

### Places And Geocoding

| Provider | Name | Method |
|---|---|---|
| Open-Meteo Geocoding | `openmeteo` | Geocoding REST API, no key required |

### Developer Sources

| Provider | Name | Method |
|---|---|---|
| GitHub | `github` | GitHub REST API |
| GitLab | `gitlab` | GitLab REST API |
| Codeberg | `codeberg` | Codeberg REST API |
| Stack Overflow | `stackoverflow` | Stack Exchange API |
| Sourcegraph | `sourcegraph` | Streaming search API, no key required |
| Hacker News | `hackernews` | Algolia HN API |
| Hugging Face | `huggingface` | Hub REST API, no key required |
| Reddit | `reddit` | Reddit API |
| npm | `npm` | npm registry API |
| PyPI | `pypi` | JSON API |
| RubyGems | `rubygems` | RubyGems search API |
| crates.io | `crates` | crates.io API |
| lib.rs | `lib_rs` | HTML scraping |
| Docker Hub | `dockerhub` | Docker Hub search API |
| pkg.go.dev | `pkg_go_dev` | HTML scraping |
| MetaCPAN | `metacpan` | MetaCPAN REST API |
| Maven Central | `maven` | Solr search API, no key required |

### Academic Sources

| Provider | Name | Method |
|---|---|---|
| arXiv | `arxiv` | Atom API |
| PubMed | `pubmed` | NCBI E-utilities |
| Semantic Scholar | `semanticscholar` | Graph API |
| CrossRef | `crossref` | REST API |
| OpenAlex | `openalex` | OpenAlex REST API, no key required |
| DOAJ | `doaj` | DOAJ public REST API, no key required |
| Zenodo | `zenodo` | Zenodo REST API, no key required |
| ORCID | `orcid` | ORCID public API (researcher profiles), no key required |

### Legal Sources

| Provider | Name | Method |
|---|---|---|
| CourtListener | `courtlistener` | Free Law Project REST API, no key required |

### Patent Sources

| Provider | Name | Method |
|---|---|---|
| Google Patents | `google_patents` | Public XHR query API, no key required |

### News Sources

| Provider | Name | Method |
|---|---|---|
| Google News | `google_news` | Public RSS feed, no key required |
| Wikinews | `wikinews` | MediaWiki API, no key required |
| Lobsters | `lobsters` | Lobste.rs JSON API, no key required |

### Social Sources

| Provider | Name | Method |
|---|---|---|
| Mastodon | `mastodon` | Mastodon public API, no key required |
| Bluesky | `bluesky` | Bluesky AppView public API, no key required |
| Lemmy | `lemmy` | Lemmy public API, no key required |

### Media Sources

| Provider | Name | Method |
|---|---|---|
| Wikimedia Commons | `wikimedia_commons` | MediaWiki API, no key required |
| Openverse | `openverse` | Openverse REST API, no key required |
| Flickr | `flickr` | Public feed API, no key required |
| Unsplash | `unsplash` | Unsplash REST API (requires `UNSPLASH_ACCESS_KEY`) |
| NASA | `nasa` | NASA Image and Video Library API, no key required |
| PeerTube | `peertube` | Public REST API, no key required |
| TVMaze | `tvmaze` | TVMaze public API, no key required |
| Radio Browser | `radio_browser` | Radio Browser public API, no key required |
| MusicBrainz | `musicbrainz` | MusicBrainz public API (recordings/artists), no key required |
| Steam | `steam` | Steam Store search API, no key required |
| TheMealDB | `themealdb` | TheMealDB public API, no key required |
| iTunes | `itunes` | iTunes Search API (podcasts), no key required |

### Finance Sources

| Provider | Name | Key Required | Free Tier |
|---|---|---|---|
| Yahoo Finance | `yahoo_finance` | No | Unofficial endpoint, no key needed |
| Alpha Vantage | `alpha_vantage` | `ALPHA_VANTAGE_API_KEY` | 25 req/day — [get key](https://www.alphavantage.co/support/#api-key) |
| Finnhub | `finnhub` | `FINNHUB_API_KEY` | 60 req/min — [get key](https://finnhub.io/register) |
| CoinGecko | `coingecko` | No | Cryptocurrency search API, no key needed |

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
YDC_API_KEY=
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

To enable You.com, set `YDC_API_KEY` and either let it participate in the default web-provider pool or explicitly target it with `providers: ["youcom"]`.

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "playwright locator best practices",
    "providers": ["youcom"],
    "params": {"num_results": 5}
  }'
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

### `GET /search/suggest`

Query autocomplete suggestions for a partial search term. Uses the public DuckDuckGo autocomplete endpoint — no API key required.

```bash
curl "http://localhost:8000/search/suggest?q=python&limit=5"
```

Returns `query`, `suggestions`, `count`, and `source` (`duckduckgo`). `limit` defaults to 8 and is capped at 20.

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
- `search_finance`
- `search_code`
- `search_news`
- `search_social`
- `search_images`
- `search_videos`
- `list_providers`

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

- `contracts.py`: request/response data models (Pydantic schemas)
- `config.py`: application settings loaded from environment variables
- `catalog.py`: provider discovery, filtering, and selection by name or tags
- `orchestrator.py`: concurrent search execution across providers and result assembly
- `merge.py`: URL canonicalization and cross-engine result deduplication
- `server.py`: FastAPI application and Uvicorn server entrypoint
- `broker.py`: MCP server exposing search tools over stdio
- `api/routes.py`: HTTP endpoint handlers (search, suggest, health, providers catalog)
- `cli.py`: interactive first-run setup wizard (metasearchmcp-setup)

Entry-point wrappers (`main.py` for HTTP, `mcp_server.py` for MCP) and legacy
compatibility shims (`aggregator.py`, `dedup.py`, `schema.py`) are kept for
backwards compatibility.

## Roadmap

- Caching and provider-aware query reuse
- Better scoring and ranking signals across providers
- Streaming aggregation responses
- Provider health telemetry
- More first-party API integrations where they improve reliability

## License

MIT
