"""Mastodon search via the public, keyless API v2 search endpoint.

Mastodon exposes an unauthenticated search endpoint on every instance:
``https://mastodon.social/api/v2/search?q=QUERY&type=statuses``. It returns
recent public posts (statuses) matching the query, each with the post text,
author account, creation date, and interaction counts.

No API key or authentication is required for public search; parsing uses the
standard library plus BeautifulSoup for stripping post HTML.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from bs4 import BeautifulSoup

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://mastodon.social/api/v2/search"
# Mastodon caps the search endpoint at 40 statuses per request.
_MAX_API_RESULTS = 40


class MastodonProvider(BaseProvider):
    """Search public posts and discussions across the fediverse via Mastodon.

    Uses the keyless API v2 search endpoint of the flagship instance
    (mastodon.social). Results are recent public statuses; each hit carries
    the author handle, a creation date, and favourite/reblog counts.
    """

    name = "mastodon"
    description = "Search public posts and discussions on Mastodon (fediverse)."
    tags: ClassVar[list[str]] = ["social", "web"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Mastodon public statuses for *query* via API v2 search."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        qp = {
            "q": query,
            "type": "statuses",
            "resolve": "false",
            "limit": limit,
        }
        async with self._client() as client:
            resp = await client.get(_SEARCH_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    @staticmethod
    def _plain_text(html_content: str) -> str:
        """Strip HTML tags from a status body and collapse whitespace."""
        if not html_content:
            return ""
        text = BeautifulSoup(html_content, "lxml").get_text(" ", strip=True)
        return " ".join(text.split())

    @staticmethod
    def _date_prefix(created_at: str | None) -> str | None:
        """Convert an API ISO-8601 timestamp to a YYYY-MM-DD prefix."""
        if not created_at:
            return None
        try:
            return (
                datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                .astimezone(UTC)
                .date()
                .isoformat()
            )
        except (TypeError, ValueError):
            return None

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the API v2 search response into structured results."""
        results: list[SearchResult] = []
        statuses = data.get("statuses") or []

        for i, status in enumerate(statuses, start=1):
            content = status.get("content", "")
            url = status.get("url", "")
            if not url:
                continue

            account = status.get("account") or {}
            acct = account.get("acct") or account.get("username") or ""
            display_name = account.get("display_name") or acct or ""
            account_url = account.get("url", "")

            snippet = self._plain_text(content)[:MAX_SNIPPET_LENGTH]

            results.append(
                SearchResult(
                    title=f"{display_name}: {self._plain_text(content)[:80]}"
                    if content
                    else display_name,
                    url=url,
                    snippet=snippet,
                    source="mastodon.social",
                    rank=i,
                    provider=self.name,
                    published_date=self._date_prefix(status.get("created_at")),
                    extra={
                        "account": acct,
                        "account_url": account_url,
                        "reblogs": status.get("reblogs_count", 0),
                        "favourites": status.get("favourites_count", 0),
                        "replies": status.get("replies_count", 0),
                    },
                ),
            )

        return ProviderResult(results=results)
