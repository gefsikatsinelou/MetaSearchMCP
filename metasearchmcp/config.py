from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"

    # Timeouts
    default_timeout: float = 10.0
    aggregator_timeout: float = 15.0

    # API keys — Google providers
    serpbase_api_key: str = ""
    serper_api_key: str = ""

    # API keys — web providers
    brave_api_key: str = ""
    tavily_api_key: str = ""

    # API keys — developer providers
    github_token: str = ""
    stackexchange_api_key: str = ""  # optional; 10k req/day vs 300 without
    reddit_client_id: str = ""  # required for Reddit search
    reddit_client_secret: str = ""  # required for Reddit search

    # API keys — academic providers
    ncbi_api_key: str = ""  # PubMed / NCBI (optional)
    semantic_scholar_api_key: str = ""  # Semantic Scholar (optional)

    # Provider control
    enabled_providers: str = ""  # comma-separated; empty = auto
    allow_unstable_providers: bool = False
    max_results_per_provider: int = 10

    def enabled_provider_list(self) -> list[str]:
        """Return explicit list of enabled providers, or empty list meaning 'auto'."""
        if not self.enabled_providers.strip():
            return []
        return [p.strip() for p in self.enabled_providers.split(",") if p.strip()]


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
