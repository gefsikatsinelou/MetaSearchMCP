"""Reddit search via the official OAuth2 API."""

from __future__ import annotations

import base64
import datetime

import httpx

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BOT_USER_AGENT, BaseProvider

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_SEARCH_URL = "https://oauth.reddit.com/search.json"
_MAX_SELFTEXT_LENGTH = 200


class RedditProvider(BaseProvider):
    """Reddit search via the official OAuth2 API.

    Requires a Reddit application (free, no review needed for script apps):
      1. Go to https://www.reddit.com/prefs/apps
      2. Create a 'script' app
      3. Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET env vars

    Reddit blocked unauthenticated API access in 2023.
    """

    name = "reddit"
    description = "Search Reddit posts, comments, and communities."
    tags = ["web", "news", "developer"]

    def __init__(self) -> None:
        """Initialize the Reddit provider with OAuth2 credentials."""
        super().__init__()
        settings = get_settings()
        self._client_id = settings.reddit_client_id
        self._client_secret = settings.reddit_client_secret

    def is_available(self) -> bool:
        """Return whether both client ID and client secret are configured."""
        return bool(self._client_id and self._client_secret)

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        credentials = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode(),
        ).decode()
        resp = await client.post(
            _TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={
                "Authorization": f"Basic {credentials}",
                "User-Agent": BOT_USER_AGENT,
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Reddit posts for *query* and return matching results."""
        async with self._client() as client:
            token = await self._get_token(client)
            qp = {
                "q": query,
                "sort": "relevance",
                "limit": min(params.num_results, self._max_results, 25),
                "type": "link",
            }
            if not params.safe_search:
                qp["include_over_18"] = "on"

            resp = await client.get(
                _SEARCH_URL,
                params=qp,
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": BOT_USER_AGENT,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict) -> ProviderResult:
        results: list[SearchResult] = []
        children = data.get("data", {}).get("children", [])

        for i, child in enumerate(children, start=1):
            post = child.get("data", {})
            title = post.get("title", "")
            url = post.get("url", "")
            permalink = "https://www.reddit.com" + post.get("permalink", "")
            subreddit = post.get("subreddit_name_prefixed", "")
            score = post.get("score", 0)
            comments = post.get("num_comments", 0)
            selftext = (post.get("selftext") or "")[:_MAX_SELFTEXT_LENGTH]
            created = post.get("created_utc")

            published = None
            if created:
                published = datetime.datetime.fromtimestamp(
                    created,
                    tz=datetime.UTC,
                ).strftime("%Y-%m-%d")

            is_self = post.get("is_self", False)
            final_url = permalink if is_self else url

            snippet_parts = [subreddit, f"Score: {score} | Comments: {comments}"]
            if selftext:
                snippet_parts.append(selftext)

            results.append(
                SearchResult(
                    title=title,
                    url=final_url,
                    snippet=" | ".join(p for p in snippet_parts if p),
                    source="reddit.com",
                    rank=i,
                    provider=self.name,
                    published_date=published,
                    extra={
                        "subreddit": subreddit,
                        "score": score,
                        "num_comments": comments,
                        "permalink": permalink,
                    },
                ),
            )

        return ProviderResult(results=results)
