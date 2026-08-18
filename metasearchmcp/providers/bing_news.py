"""Bing News search via the public, keyless RSS endpoint.

Bing exposes an unauthenticated RSS feed for its news vertical:
``https://www.bing.com/news/search?q=QUERY&qft=sortbydate%3d%221%22&form=PTFNR&format=RSS``

The feed returns recent headlines matching the query, each with title,
publication date, a snippet, the publishing outlet, and a Bing redirect
link that wraps the original article URL.

No API key is required; parsing uses only the standard library.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import ClassVar
from urllib.parse import parse_qs, urlparse

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_RSS_URL = "https://www.bing.com/news/search"
# Bing News RSS returns at most 30 items per request.
_MAX_FEED_RESULTS = 30


def _local(tag: str) -> str:
    """Return the local part of an XML tag, ignoring any namespace prefix."""
    return tag.rsplit("}", 1)[-1]


class BingNewsProvider(BaseProvider):
    """Search recent news headlines and articles via Bing News RSS.

    Uses the public RSS search feed — no API key or authentication needed.
    Results are ordered by date; each hit carries the publishing outlet,
    a publication date, and a link to the original article.

    Note: per Microsoft's RSS terms, results are intended for personal,
    non-commercial use (e.g. rendered inside an RSS aggregator).
    """

    name = "bing_news"
    description = "Search recent news headlines and articles via Bing News RSS."
    tags: ClassVar[list[str]] = ["news", "web"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Bing News for *query* via the public RSS feed."""
        feed_params = {
            "q": query,
            "qft": 'sortbydate="1"',
            "form": "PTFNR",
            "format": "RSS",
        }
        async with self._client() as client:
            resp = await client.get(_RSS_URL, params=feed_params)
            resp.raise_for_status()
            xml_text = resp.text

        limit = min(params.num_results, self._max_results, _MAX_FEED_RESULTS)
        return self._parse(xml_text, limit)

    @staticmethod
    def _article_url(link: str) -> str:
        """Extract the underlying article URL from a Bing redirect link.

        The feed's ``<link>`` entries point at Bing's click-tracking
        endpoint with the real article URL encoded in the ``url`` query
        parameter; when that parameter is absent the link is returned
        unchanged.
        """
        encoded = parse_qs(urlparse(link).query).get("url", [""])[0]
        return encoded or link

    @staticmethod
    def _parse_pub_date(pub_date: str | None) -> str | None:
        """Convert an RFC 2822 feed date to a YYYY-MM-DD prefix."""
        if not pub_date:
            return None
        try:
            return parsedate_to_datetime(pub_date).date().isoformat()
        except (TypeError, ValueError, OverflowError):
            return None

    def _parse(self, xml_text: str, limit: int) -> ProviderResult:
        """Parse the RSS feed XML into structured search results."""
        root = ET.fromstring(xml_text)
        results: list[SearchResult] = []

        items = [element for element in root.iter() if _local(element.tag) == "item"]
        for i, item in enumerate(items[:limit], start=1):
            fields = {_local(child.tag): child for child in item}
            title_el = fields.get("title")
            link_el = fields.get("link")
            if title_el is None or link_el is None:
                continue

            title = (title_el.text or "").strip()
            redirect_url = (link_el.text or "").strip()
            if not title or not redirect_url:
                continue

            description_el = fields.get("description")
            snippet = (
                " ".join((description_el.text or "").split())
                if description_el is not None
                else ""
            )
            source_el = fields.get("Source")
            source_name = (
                (source_el.text or "").strip() if source_el is not None else ""
            )

            pub_date_el = fields.get("pubDate")
            published = self._parse_pub_date(
                pub_date_el.text if pub_date_el is not None else None,
            )

            results.append(
                SearchResult(
                    title=title,
                    url=self._article_url(redirect_url),
                    snippet=snippet,
                    source=source_name or "bing.com",
                    rank=i,
                    provider=self.name,
                    published_date=published,
                    extra={
                        "outlet": source_name,
                        "redirect_url": redirect_url,
                    },
                ),
            )

        return ProviderResult(results=results)
