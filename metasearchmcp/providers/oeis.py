"""Search the On-Line Encyclopedia of Integer Sequences (OEIS).

OEIS (``oeis.org``) is the canonical reference for integer sequences: roughly
400,000 sequences, each carrying the terms themselves, a descriptive name,
formulas, comments, references and cross-references.  Its search endpoint
accepts a comma-separated list of terms, an A-number (``A000045``) or free-text
keywords, and answers in JSON when asked for it::

    GET https://oeis.org/search?q=1,2,3,5,8,13&fmt=json

The payload is a bare JSON array of the matching records — ``null`` when a
query has no matches, which this provider reports as an empty page rather than
as a failure.  Each record carries the sequence number (rendered here as the
canonical ``A000045`` identifier used on oeis.org), the legacy M/N id, the
name, the terms, the offset, keyword flags (``nonn``, ``easy``, ``core``,
``hear``, ...), the author line, the creation/revision timestamps, and the
comment/formula/reference/link/cross-reference counts.

This complements the mathematics-literature providers (zbMATH Open, arXiv,
OpenAlex, DBLP) with a direct dictionary-style lookup of a numerical sequence
by its terms.  No API key or registration is required; OEIS asks for a
descriptive User-Agent and at most one request per second, which this
single-request provider respects.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://oeis.org/search"
# The JSON search endpoint returns at most this many records per request.
_MAX_API_RESULTS = 10
# Terms copied into a snippet before the list is elided.
_SNIPPET_TERM_LIMIT = 10
# Characters of the leading comment copied into a snippet.
_SNIPPET_COMMENT_LENGTH = 160
# Keyword flags listed in a snippet.
_SNIPPET_KEYWORD_LIMIT = 6
# Characters of a sequence name kept in the result title.
_TITLE_NAME_LIMIT = 140


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _string(value: object) -> str:
    """Return a plain string field, or an empty string."""
    return value if isinstance(value, str) else ""


def _entries(value: object) -> list[Any]:
    """Return a list field, or an empty list for missing/junk values."""
    return value if isinstance(value, list) else []


def _int(value: object) -> int | None:
    """Return a non-negative integer counter, ignoring booleans and junk."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    count = int(value)
    return count if count >= 0 else None


class OeisProvider(BaseProvider):
    """Search the On-Line Encyclopedia of Integer Sequences.

    Keyless.  Queries the OEIS JSON search endpoint in a single request and
    returns one hit per matching sequence, carrying the A-number, legacy id,
    name, initial terms, offset, keyword flags, author line, timestamps and
    the comment/formula/reference/link counts, and linking to the sequence's
    canonical ``https://oeis.org/A000045`` page.
    """

    name = "oeis"
    description = (
        "Search the On-Line Encyclopedia of Integer Sequences (OEIS) by "
        "terms, A-number or keywords — sequence names, initial terms, "
        "offset, keyword flags and authors, no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "web", "math", "reference"]

    @staticmethod
    def _number(item: dict[str, Any]) -> int | None:
        """Return the sequence number as an int, accepting numeric strings."""
        raw = item.get("number")
        if isinstance(raw, bool):
            return None
        if isinstance(raw, int):
            return raw if raw >= 0 else None
        try:
            parsed = int(str(raw).strip())
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None

    @staticmethod
    def _terms(item: dict[str, Any]) -> list[str]:
        """Return the sequence terms as a list of strings."""
        raw = _clean(item.get("data"))
        if not raw:
            return []
        return [term.strip() for term in raw.split(",") if term.strip()]

    @staticmethod
    def _keywords(item: dict[str, Any]) -> list[str]:
        """Return the sequence's keyword flags, deduplicated and ordered."""
        raw = _clean(item.get("keyword"))
        if not raw:
            return []
        keywords: list[str] = []
        for keyword in raw.split(","):
            label = keyword.strip()
            if label and label not in keywords:
                keywords.append(label)
        return keywords

    @staticmethod
    def _author(item: dict[str, Any]) -> str:
        """Return the author line with OEIS wiki-style underscores removed."""
        return _clean(_string(item.get("author")).replace("_", ""))

    @staticmethod
    def _title(a_number: str, name: str, terms: list[str]) -> str:
        """Compose the result title from the A-number and sequence name."""
        label = name or ", ".join(terms)
        if label:
            return f"{a_number}: {label[:_TITLE_NAME_LIMIT]}"
        return a_number

    @classmethod
    def _snippet(
        cls,
        terms: list[str],
        comments: list[Any],
        offset: str,
        keywords: list[str],
        author: str,
    ) -> str:
        """Compose the snippet for a single sequence."""
        parts: list[str] = []
        if terms:
            shown = ", ".join(terms[:_SNIPPET_TERM_LIMIT])
            if len(terms) > _SNIPPET_TERM_LIMIT:
                shown = f"{shown}, ..."
            parts.append(f"Terms: {shown}")
        if comments:
            excerpt = _clean(comments[0])[:_SNIPPET_COMMENT_LENGTH]
            if excerpt:
                parts.append(excerpt)
        if offset:
            parts.append(f"Offset: {offset}")
        if keywords:
            parts.append(f"Keywords: {', '.join(keywords[:_SNIPPET_KEYWORD_LIMIT])}")
        if author:
            parts.append(f"Author: {author}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(self, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from an OEIS record."""
        number = self._number(item)
        if number is None:
            return None

        a_number = f"A{number:06d}"
        name = _clean(item.get("name"))
        terms = self._terms(item)
        comments = _entries(item.get("comment"))
        formulas = _entries(item.get("formula"))
        links = _entries(item.get("link"))
        references = _entries(item.get("reference"))
        xrefs = _entries(item.get("xref"))
        keywords = self._keywords(item)
        author = self._author(item)
        offset = _clean(item.get("offset"))
        legacy_id = _clean(item.get("id"))
        created = self._iso_date_prefix(_string(item.get("created")))
        updated = self._iso_date_prefix(_string(item.get("time")))
        url = f"https://oeis.org/{a_number}"

        return SearchResult(
            title=self._title(a_number, name, terms),
            url=url,
            snippet=self._snippet(terms, comments, offset, keywords, author),
            source="oeis.org",
            rank=rank,
            provider=self.name,
            published_date=created,
            extra={
                "a_number": a_number,
                "legacy_id": legacy_id or None,
                "name": name,
                "terms": terms,
                "offset": offset or None,
                "keywords": keywords,
                "author": author or None,
                "comments": len(comments),
                "formulas": len(formulas),
                "links": len(links),
                "references": len(references),
                "xrefs": len(xrefs),
                "created": created,
                "updated": updated,
                "url": url,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse an OEIS JSON search response into structured results.

        The endpoint answers with a bare array of records, or ``null`` when
        nothing matches; any other shape yields an empty page.
        """
        results: list[SearchResult] = []
        if not isinstance(data, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in data:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            built = self._build_result(item, len(results) + 1)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the OEIS for sequences matching *query*.

        A blank query performs no request.  The index's own relevance order is
        preserved in the returned results; the JSON endpoint returns at most
        ten records, so that is the effective page size.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={"q": cleaned, "fmt": "json"},
            )
            resp.raise_for_status()
            data: object = resp.json()

        return self._parse(data, limit=limit)
