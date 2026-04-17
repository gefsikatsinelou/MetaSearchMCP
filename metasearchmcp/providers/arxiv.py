from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider

_API_URL = "https://export.arxiv.org/api/query"
_NS = {"atom": "http://www.w3.org/2005/Atom"}


class ArxivProvider(BaseProvider):
    """arXiv academic paper search via the public Atom API.

    No authentication required. Rate limit: ~3 req/sec, 1 req/3s recommended.
    """

    name = "arxiv"
    description = "Search arXiv preprints across physics, mathematics, computer science, and more."
    tags = ["academic", "web"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        qp = {
            "search_query": f"all:{query}",
            "max_results": str(min(params.num_results, self._max_results)),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }

        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            xml_text = resp.text

        return self._parse(xml_text)

    def _parse(self, xml_text: str) -> ProviderResult:
        results: list[SearchResult] = []

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return ProviderResult()

        for i, entry in enumerate(root.findall("atom:entry", _NS), start=1):
            title_el = entry.find("atom:title", _NS)
            summary_el = entry.find("atom:summary", _NS)
            id_el = entry.find("atom:id", _NS)
            published_el = entry.find("atom:published", _NS)

            title = title_el.text.strip() if title_el is not None else ""
            snippet = summary_el.text.strip() if summary_el is not None else ""
            arxiv_url = id_el.text.strip() if id_el is not None else ""
            published = published_el.text[:10] if published_el is not None else None

            # Collect authors
            authors = [
                a.findtext("atom:name", "", _NS)
                for a in entry.findall("atom:author", _NS)
            ]

            results.append(SearchResult(
                title=title,
                url=arxiv_url,
                snippet=snippet[:400],
                source="arxiv.org",
                rank=i,
                provider=self.name,
                published_date=published,
                extra={"authors": authors},
            ))

        return ProviderResult(results=results)
