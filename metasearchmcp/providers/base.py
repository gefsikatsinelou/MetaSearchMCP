from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams


class BaseProvider(ABC):
    """Abstract base for all search providers."""

    name: str = ""
    # Tags help the aggregator filter by intent (e.g. "google", "academic")
    tags: list[str] = []

    def __init__(self) -> None:
        settings = get_settings()
        self._timeout = settings.default_timeout
        self._max_results = settings.max_results_per_provider

    # Bot-friendly UA for API calls
    _API_HEADERS = {
        "User-Agent": "metasearchmcp/0.1 (metasearch; +https://github.com/your-org/metasearchmcp)",
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
        return f"<Provider name={self.name!r}>"
