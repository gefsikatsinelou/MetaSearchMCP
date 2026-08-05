"""Google News search via the public, keyless RSS endpoint.

Google News exposes an unauthenticated RSS feed for keyword searches:
``https://news.google.com/rss/search?q=QUERY``. The feed returns up to
100 recent headlines matching the query, each with title, publication
date, source outlet, and a Google News redirect link to the article.

No API key is required; parsing uses only the standard library.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import ClassVar

from bs4 import BeautifulSoup

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_RSS_URL = "https://news.google.com/rss/search"
# Google News RSS returns at most 100 items per query.
_MAX_FEED_RESULTS = 100


def _local(tag: str) -> str:
    """Return the local part of an XML tag, ignoring any namespace prefix."""
    return tag.rsplit("}", 1)[-1]


class GoogleNewsProvider(BaseProvider):
    """Search recent news headlines and articles via Google News RSS.

    Uses the public RSS search feed — no API key or authentication needed.
    Results are ordered by relevance; each hit carries the publishing
    outlet, a publication date, and the Google News article link.
    """

    name = "google_news"
    description = "Search recent news headlines and articles via Google News RSS."
    tags: ClassVar[list[str]] = ["news", "web"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Google News for *query* via the public RSS feed."""
        language = self._language_code(params.language)
        country = self.country_code(params.country)
        feed_params = {
            "q": query,
            "hl": f"{language}-{country}",
            "gl": country,
            "ceid": f"{country}:{language}",
        }
        async with self._client() as client:
            resp = await client.get(_RSS_URL, params=feed_params)
            resp.raise_for_status()
            xml_text = resp.text

        limit = min(params.num_results, self._max_results, _MAX_FEED_RESULTS)
        return self._parse(xml_text, limit)

    @staticmethod
    def _parse_description(description: str) -> tuple[str, str]:
        """Extract (snippet, source_name) from an item description.

        The RSS description is HTML: an anchor with the headline followed
        by a ``<font>`` element naming the publishing outlet.
        """
        if not description:
            return "", ""
        soup = BeautifulSoup(description, "lxml")
        snippet = " ".join(soup.get_text(" ", strip=True).split())
        source = soup.find("font")
        source_name = (
            " ".join(source.get_text(" ", strip=True).split()) if source else ""
        )
        return snippet, source_name

    @staticmethod
    def _parse_pub_date(pub_date: str | None) -> str | None:
        """Convert an RFC 2822 feed date to a YYYY-MM-DD prefix."""
        if not pub_date:
            return None
        try:
            return parsedate_to_datetime(pub_date).date().isoformat()
        except (TypeError, ValueError, OverflowError):
            return None

    @classmethod
    def _clean_title(cls, title: str, source_name: str) -> str:
        """Strip the trailing ``" - Source"`` suffix from a feed title."""
        if source_name and title.endswith(f" - {source_name}"):
            return title[: -(len(source_name) + 3)].strip()
        return title.strip()

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
            url = (link_el.text or "").strip()
            if not title or not url:
                continue

            source_el = fields.get("source")
            source_name = (
                (source_el.text or "").strip() if source_el is not None else ""
            )
            source_url = source_el.get("url", "") if source_el is not None else ""

            description = fields.get("description")
            snippet, desc_source = self._parse_description(
                description.text if description is not None else "",
            )
            if not source_name and desc_source:
                source_name = desc_source

            pub_date = fields.get("pubDate")
            published = self._parse_pub_date(
                pub_date.text if pub_date is not None else None,
            )

            results.append(
                SearchResult(
                    title=self._clean_title(title, source_name),
                    url=url,
                    snippet=snippet,
                    source=source_name or "news.google.com",
                    rank=i,
                    provider=self.name,
                    published_date=published,
                    extra={
                        "outlet": source_name,
                        "outlet_url": source_url,
                    },
                ),
            )

        return ProviderResult(results=results)
