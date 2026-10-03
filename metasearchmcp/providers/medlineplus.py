"""Consumer health topic search via the keyless MedlinePlus web service.

``MedlinePlus`` (https://medlineplus.gov), produced by the U.S. National
Library of Medicine, exposes a keyless search endpoint that returns
authoritative, plain-language health information::

    GET https://wsearch.nlm.nih.gov/ws/query
        ?db=healthTopics&term=diabetes&retmax=10

The response is XML: an ``nlmSearchResult`` root whose ``list`` holds one
``document`` per matching health topic.  Each document carries a canonical
``url`` plus named ``content`` fields (``title``, ``snippet``/``FullSummary``,
``organizationName``, ``altTitle``, ``mesh`` and ``groupName``).  Field text
is HTML-escaped markup, so tags are stripped here before returning results.
No API key is required.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://wsearch.nlm.nih.gov/ws/query"
# The healthTopics database covers diseases, conditions, wellness and more.
_DB = "healthTopics"
# MedlinePlus returns long plain-language summaries; cap results regardless.
_MAX_RESULTS = 25

_BLOCK_TAG_RE = re.compile(
    r"</?(?:p|div|ul|ol|li|br|hr|h[1-6]|tr|td|th|table|section|article|"
    r"blockquote|dl|dt|dd)\b[^>]*>",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(value: str | None) -> str:
    """Return *value* with HTML tags removed and whitespace collapsed.

    Block-level tags are replaced with a space so that adjacent paragraphs do
    not run together, while inline tags (e.g. ``<span>`` highlighting) are
    dropped without inserting spurious spacing.
    """
    if not value:
        return ""
    text = _BLOCK_TAG_RE.sub(" ", value)
    text = _TAG_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


class MedlinePlusProvider(BaseProvider):
    """Search consumer health topics in the keyless MedlinePlus database.

    Each hit is a curated health topic page from the U.S. National Library of
    Medicine, exposing a plain-language summary, the publishing organization,
    alternative names, MeSH terms and the topic's health categories so agents
    get structured medical-reference facts rather than raw prose.
    """

    name = "medlineplus"
    description = (
        "Search MedlinePlus consumer health topics (diseases, conditions, "
        "wellness) from the U.S. National Library of Medicine, returning "
        "plain-language summaries, alternative names, MeSH terms and topic "
        "groups, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "medical", "health", "reference"]

    def _build_result(
        self,
        document: ET.Element,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw MedlinePlus document."""
        values: dict[str, list[str]] = {}
        for content in document.findall("content"):
            field = content.attrib.get("name", "")
            if not field:
                continue
            values.setdefault(field, []).append(content.text or "")

        title = _strip_html(values.get("title", [""])[0])
        if not title:
            alt_titles_raw = values.get("altTitle", [])
            title = _strip_html(alt_titles_raw[0]) if alt_titles_raw else ""
        if not title:
            return None

        url = (document.attrib.get("url") or "").strip()
        if not url:
            return None

        # ``snippet`` is a compact summary; ``FullSummary`` is the fallback.
        summary_values = values.get("snippet") or values.get("FullSummary") or []
        snippet = _strip_html(summary_values[0]) if summary_values else ""

        organization = _strip_html(values.get("organizationName", [""])[0])
        if organization:
            snippet = f"{organization} | {snippet}" if snippet else organization
        snippet = snippet[:MAX_SNIPPET_LENGTH]

        alt_titles = [
            cleaned
            for cleaned in (_strip_html(item) for item in values.get("altTitle", []))
            if cleaned
        ]
        groups = [
            cleaned
            for cleaned in (_strip_html(item) for item in values.get("groupName", []))
            if cleaned
        ]
        mesh_raw = values.get("mesh", [])
        mesh = _strip_html(mesh_raw[0]) if mesh_raw else ""

        return SearchResult(
            title=title,
            url=url,
            snippet=snippet,
            source="medlineplus.gov",
            rank=rank,
            provider=self.name,
            extra={
                "organization": organization or None,
                "alt_titles": alt_titles,
                "groups": groups,
                "mesh": mesh or None,
            },
        )

    def _parse(self, xml_text: str, limit: int) -> list[SearchResult]:
        """Parse a MedlinePlus XML response into ranked results, capped at *limit*."""
        results: list[SearchResult] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return results

        container = root.find("list")
        if container is None:
            return results

        for document in container.findall("document"):
            if len(results) >= limit:
                break
            built = self._build_result(document, len(results) + 1)
            if built is not None:
                results.append(built)

        return results

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search MedlinePlus health topics matching *query*.

        A blank query performs no request, and a malformed XML response yields
        an empty result set rather than an exception.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_RESULTS)
        api_params = {"db": _DB, "term": cleaned, "retmax": str(limit)}

        async with self._client() as client:
            resp = await client.get(_API_URL, params=api_params)
            resp.raise_for_status()
            xml_text = resp.text

        return ProviderResult(results=self._parse(xml_text, limit))
