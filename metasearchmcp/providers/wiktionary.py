"""Wiktionary search via the MediaWiki Action API.

Wiktionary is the free collaborative dictionary and thesaurus run by the
Wikimedia Foundation, covering definitions, pronunciations, etymologies, and
translations.  Its MediaWiki Action API requires no authentication and returns
clean JSON:

``GET https://en.wiktionary.org/w/api.php?action=query&generator=search&...``

Unlike Wikipedia/Wikiquote, Wiktionary does not populate the TextExtracts
``prop=extracts`` field, so this provider fetches the entry's raw wikitext via
``prop=revisions`` instead and extracts the numbered definition lines (the
``#`` list items under each part-of-speech heading), stripping MediaWiki
markup into a plain-text snippet.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://en.wiktionary.org/w/api.php"

# How many definition lines to include per entry (in addition to the headword
# line itself, which the API returns as the page title).
_MAX_DEFINITION_LINES = 2


class WiktionaryProvider(BaseProvider):
    """Search dictionary definitions on Wiktionary.

    Keyless. Uses ``generator=search`` with ``prop=revisions`` so each result
    carries the matching entry's primary definitions as the snippet (stripped
    of MediaWiki markup and truncated to a consistent length), along with a
    direct link to the Wiktionary entry.
    """

    name = "wiktionary"
    description = (
        "Search dictionary definitions, etymologies, and translations in "
        "Wiktionary, Wikimedia's free collaborative dictionary, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "knowledge", "reference"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Wiktionary for *query* and return matching dictionary entries."""
        qp = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrlimit": str(min(params.num_results, self._max_results)),
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "format": "json",
            "utf8": "1",
        }

        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the API response into structured search results."""
        results: list[SearchResult] = []
        pages = data.get("query", {}).get("pages", {})
        if not isinstance(pages, dict):
            return ProviderResult(results=results)

        # Sort by index to preserve search relevance order (MediaWiki returns
        # pages keyed by pageid with an ``index`` field from generator=search).
        ordered = sorted(
            (p for p in pages.values() if isinstance(p, dict)),
            key=lambda p: p.get("index", 0),
        )

        for rank, page in enumerate(ordered, start=1):
            title = page.get("title", "")
            if not title:
                continue
            slug = title.replace(" ", "_")
            url = f"https://en.wiktionary.org/wiki/{slug}"

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=self._extract_snippet(self._revision_content(page)),
                    source="en.wiktionary.org",
                    rank=rank,
                    provider=self.name,
                    extra={"pageid": page.get("pageid", 0)},
                ),
            )

        return ProviderResult(results=results)

    @staticmethod
    def _revision_content(page: dict[str, Any]) -> str:
        """Return the main-slot wikitext of a page from a revisions response."""
        revisions = page.get("revisions") or []
        if not revisions:
            return ""
        slots = revisions[0].get("slots") or {}
        main = slots.get("main") or {}
        return main.get("*") or ""

    @classmethod
    def _extract_snippet(cls, content: str) -> str:
        """Extract the primary definitions from entry wikitext as plain text.

        Wiktionary entries store definitions as numbered ``#`` list items
        (e.g. ``# An unsought, unintended ... discovery``).  The first couple
        of definition lines after any redirect handling are joined into the
        snippet, with MediaWiki markup stripped and the result truncated to a
        consistent length.
        """
        definitions: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("#redirect"):
                # Redirect pages carry no definitions of their own.
                continue
            if not stripped.startswith("#"):
                continue
            body = re.sub(r"^#+\s*", "", stripped)
            if not body:
                continue
            cleaned = cls._clean_wikitext(body)
            if cleaned:
                definitions.append(cleaned)
            if len(definitions) >= _MAX_DEFINITION_LINES:
                break

        return " ".join(definitions)[:MAX_SNIPPET_LENGTH]

    @staticmethod
    def _clean_wikitext(text: str) -> str:
        """Strip common MediaWiki markup from a single definition line."""
        # Links: [[target|display]] -> display, then [[target]] -> target.
        text = re.sub(r"\[\[([^\]|]*)\|([^\]]*)\]\]", r"\2", text)
        text = re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)
        # Templates such as {{taxlink|...}} and {{lb|en|...}}.
        text = re.sub(r"\{\{[^{}]*\}\}", "", text)
        # Bold/italic markers and HTML-ish tags.
        text = re.sub(r"''+", "", text)
        text = re.sub(r"<[^>]+>", "", text)
        return re.sub(r"\s+", " ", text).strip()
