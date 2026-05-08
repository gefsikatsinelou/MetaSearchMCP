"""Abstract base for all search providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import httpx

from metasearchmcp import __version__
from metasearchmcp.config import get_settings

if TYPE_CHECKING:
    from metasearchmcp.contracts import ProviderResult, SearchParams

PROJECT_URL = "https://github.com/gefsikatsinelou/MetaSearchMCP"
API_USER_AGENT = f"metasearchmcp/{__version__} (metasearch; +{PROJECT_URL})"
BOT_USER_AGENT = f"metasearchmcp/{__version__} (metasearch bot; +{PROJECT_URL})"


class BaseProvider(ABC):
    """Abstract base for all search providers."""

    name: str = ""
    description: str = ""
    # Tags help the aggregator filter by intent (e.g. "google", "academic")
    tags: list[str] = []

    def __init__(self) -> None:
        """Initialize provider with settings-derived timeout and max results."""
        settings = get_settings()
        self._timeout = settings.default_timeout
        self._max_results = settings.max_results_per_provider

    # Bot-friendly UA for API calls
    _API_HEADERS = {
        "User-Agent": API_USER_AGENT,
    }
    # Browser-like UA for HTML scraping
    _SCRAPER_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
    }

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            headers=self._API_HEADERS,
        )

    def _scraper_client(self) -> httpx.AsyncClient:
        """HTTP client with browser-like headers for HTML scraping."""
        return httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            headers=self._SCRAPER_HEADERS,
        )

    @abstractmethod
    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Execute a search and return structured results."""
        ...

    def is_available(self) -> bool:
        """Return False if the provider cannot run (e.g. missing API key)."""
        return True

    def __repr__(self) -> str:
        """Return a developer-friendly representation of the provider."""
        return f"<Provider name={self.name!r}>"
