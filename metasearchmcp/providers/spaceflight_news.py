"""Spaceflight News API search provider (keyless public API).

The Spaceflight News API (api.spaceflightnewsapi.net/v4) is a community-run
index of spaceflight and aerospace news articles from dozens of outlets
(NASA, ESA, SpaceX, Ars Technica, and more). Its public v4 endpoint requires
no API key:

``GET https://api.spaceflightnewsapi.net/v4/articles/?search=QUERY&limit=N``

Each hit carries the article title, canonical URL, publishing news site,
summary, authors, and publication timestamp. The provider is keyless, uses
only the shared httpx client, and tags itself ``news``/``space`` so it can be
filtered from the generic web pool or combined with other news providers.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.spaceflightnewsapi.net/v4/articles"
# The v4 API accepts at most 100 articles per page.
_MAX_API_RESULTS = 100


class SpaceflightNewsProvider(BaseProvider):
    """Search spaceflight and aerospace news articles.

    Keyless. Uses the public Spaceflight News API v4 (``/articles``) to find
    articles matching the query. Each hit carries the article title, URL,
    publishing news site, summary, authors, and publication date.
    """

    name = "spaceflight_news"
    description = (
        "Search spaceflight and aerospace news articles — title, news site, "
        "summary, and authors via the keyless Spaceflight News API."
    )
    tags: ClassVar[list[str]] = ["news", "space", "web"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    def _parse(
        self,
        data: dict[str, Any] | None,
        limit: int | None = None,
    ) -> ProviderResult:
        """Parse the v4 /articles response into structured results."""
        results: list[SearchResult] = []
        max_results = limit or self._max_results
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        articles = data.get("results") or []
        if not isinstance(articles, list):
            return ProviderResult(results=results)

        for i, article in enumerate(articles, start=1):
            if i > max_results:
                break
            if not isinstance(article, dict):
                continue
            title = self._clean(article.get("title"))
            url = self._clean(article.get("url"))
            if not title or not url:
                continue

            news_site = self._clean(article.get("news_site"))
            summary = self._clean(article.get("summary"))
            published = self._clean(article.get("published_at"))
            authors = [
                str(author.get("name")).strip()
                for author in (article.get("authors") or [])
                if isinstance(author, dict) and str(author.get("name")).strip()
            ]
            date_prefix = (
                published[:10] if len(published) >= 10 else (published or None)
            )

            snippet_parts: list[str] = []
            if summary:
                snippet_parts.append(summary[:MAX_SNIPPET_LENGTH])
            if news_site:
                snippet_parts.append(f"Source: {news_site}")
            if authors:
                snippet_parts.append(f"By: {', '.join(authors[:3])}")

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source=news_site or "spaceflightnewsapi.net",
                    rank=i,
                    provider=self.name,
                    published_date=date_prefix,
                    extra={
                        "news_site": news_site,
                        "authors": authors,
                        "published_at": published,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the Spaceflight News API for articles matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(_API_URL, params={"search": query, "limit": limit})
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit)
