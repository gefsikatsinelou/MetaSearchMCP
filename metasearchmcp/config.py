"""Application configuration and settings management."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

USER_CONFIG_DIR: Path = Path.home() / ".metasearchmcp"
USER_CONFIG_FILE: Path = USER_CONFIG_DIR / "config.env"
SERPBASE_DASHBOARD_URL: str = "https://serpbase.dev/dashboard/api-keys"
SERPBASE_API_URL: str = "https://api.serpbase.dev/google/search"

# Shared user-facing error message used by both MCP broker and HTTP routes.
NO_GOOGLE_PROVIDER_MSG: str = (
    "No Google provider available. "
    "Enable ALLOW_UNSTABLE_PROVIDERS=true for direct Google, "
    "or set SERPBASE_API_KEY / SERPER_API_KEY."
)


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env files."""

    model_config = SettingsConfigDict(
        # User config (~/.metasearchmcp/config.env) is the base;
        # a local .env in the working directory overrides it.
        env_file=[str(USER_CONFIG_FILE), ".env"],
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"

    # CORS — comma-separated list of allowed origins. "*" allows all (dev default).
    # Production example: CORS_ORIGINS=https://app.example.com,https://admin.example.com
    cors_origins: str = "*"

    # Timeouts
    default_timeout: float = 10.0
    aggregator_timeout: float = 15.0

    # API keys — Google providers
    serpbase_api_key: str = ""
    serper_api_key: str = ""

    # API keys — web providers
    brave_api_key: str = ""

    # API keys — developer providers
    github_token: str = ""
    stackexchange_api_key: str = ""  # optional; 10k req/day vs 300 without
    reddit_client_id: str = ""  # required for Reddit search
    reddit_client_secret: str = ""  # required for Reddit search

    # API keys — academic providers
    ncbi_api_key: str = ""  # PubMed / NCBI (optional)
    semantic_scholar_api_key: str = ""  # Semantic Scholar (optional)

    # API keys — finance providers
    alpha_vantage_api_key: str = ""  # Alpha Vantage (optional; 25 req/day free)
    finnhub_api_key: str = ""  # Finnhub (optional; 60 req/min free)

    # Provider control
    enabled_providers: str = ""  # comma-separated; empty = auto
    allow_unstable_providers: bool = False
    max_results_per_provider: int = 10

    def enabled_provider_list(self) -> list[str]:
        """Return explicit list of enabled providers, or empty list meaning 'auto'."""
        raw = self.enabled_providers.strip()
        if not raw:
            return []
        return list(
            dict.fromkeys(p.strip().lower() for p in raw.split(",") if p.strip()),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the global Settings singleton, creating it on first call."""
    return Settings()
