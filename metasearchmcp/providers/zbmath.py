"""zbMATH Open mathematical-literature search.

zbMATH Open (``zbmath.org``) is the reviewing and abstracting service for pure
and applied mathematics.  It indexes journal articles, books, conference
papers and preprints from 1868 onwards, each carrying a Zbl number, an author
list, an MSC classification and — where the licence allows — a review or an
author summary.  The index is queryable through a public, keyless REST API::

    GET https://api.zbmath.org/v1/document/_search
        ?search_string=QUERY&results_per_page=N&page=0

The search matches titles, author names, review text and classifications, and
it is case-insensitive.  A query without matches is answered with HTTP 404 and
a ``null`` result list, which this provider reports as an empty page rather
than as a failure.

Record fields are nested: ``title`` is an object (``title``/``subtitle``/
``original``), authors live under ``contributors``, the publication venue
under ``source`` (``series`` for journals, ``book`` for books) and the review
under ``editorial_contributions``.  Restricted review or language fields are
replaced by the API with a licensing placeholder, which carries no
information and is dropped here.  Titles and review text are written in
LaTeX, so inline markup is stripped before it reaches a snippet.

This complements the existing preprint and bibliography providers with the
mathematics literature (Zbl number, MSC codes, review excerpts).  No API key
is required.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.zbmath.org/v1/document/_search"
# Landing page for a record on zbmath.org; used when the API omits the URL.
_DOCUMENT_URL = "https://zbmath.org/"

# The API pages its result lists; keep pages small for agents.
_MAX_API_RESULTS = 30
# Oversample hits so that local re-ranking still fills a full page.
_RANK_OVERSAMPLE = 3
# Characters of the review/summary text copied into the snippet.
_SNIPPET_REVIEW_LENGTH = 180
# Authors listed in a snippet before the list is closed with an "et al.".
_SNIPPET_AUTHOR_LIMIT = 3
# MSC classifications surfaced in a snippet.
_SNIPPET_MSC_LIMIT = 3

# The API substitutes this placeholder for text it may not redistribute.
_UNAVAILABLE_MARKER = "contents unavailable due to conflicting licenses"

# Inline LaTeX markup (``\textit{...}``, ``\emph{...}``) found in titles and
# review text, plus the escaped delimiters (``\(``, ``\[``) around formulas.
_LATEX_COMMAND_RE = re.compile(r"\\[a-zA-Z]+\s*")
_LATEX_ESCAPE_RE = re.compile(r"\\([()\[\]{}])")
_WORD_RE = re.compile(r"[a-z0-9]+")


class ZbMathProvider(BaseProvider):
    """Search zbMATH Open for mathematical literature.

    Keyless.  Queries the zbMATH Open REST API in a single request, then
    deduplicates by Zbl number and re-ranks locally so title matches lead the
    page.  Each hit carries the Zbl number, authors, year, document type,
    journal or book source, MSC classifications, a review or summary excerpt
    and the DOI/arXiv identifier, and links to the record's zbMATH page.
    """

    name = "zbmath"
    description = (
        "Search zbMATH Open — the mathematical literature index (journal "
        "articles, books, conference papers) with authors, year, venue, MSC "
        "classification, reviews and DOIs via the keyless REST API."
    )
    tags: ClassVar[list[str]] = ["academic", "web", "math"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @classmethod
    def _plain(cls, value: object) -> str:
        """Collapse whitespace and drop inline LaTeX markup from *value*.

        Titles and review text arrive as LaTeX fragments; the inline commands
        and the braces they introduce are removed, while the words they wrap
        and the escaped formula delimiters are kept.
        """
        text = cls._clean(value)
        if not text:
            return ""
        text = _LATEX_COMMAND_RE.sub("", text)
        text = _LATEX_ESCAPE_RE.sub(r"\1", text)
        text = text.replace("{", "").replace("}", "").replace("~", " ")
        return cls._clean(text)

    @staticmethod
    def _tokens(query: str) -> list[str]:
        """Return the lowercase alphanumeric tokens of *query*."""
        return _WORD_RE.findall(query.lower())

    @classmethod
    def _title(cls, item: dict[str, Any]) -> str:
        """Return the display title of a record.

        Titles are objects with an optional subtitle; the original-language
        title is only used when the translated title is missing.
        """
        raw = item.get("title")
        if isinstance(raw, dict):
            parts = [cls._plain(raw.get("title")), cls._plain(raw.get("subtitle"))]
            joined = ": ".join(part for part in parts if part)
            return joined or cls._plain(raw.get("original"))
        return cls._plain(raw)

    @classmethod
    def _names(cls, item: dict[str, Any]) -> list[str]:
        """Return the author names of a record, falling back to its editors."""
        contributors = item.get("contributors")
        if not isinstance(contributors, dict):
            return []
        for field in ("authors", "editors"):
            names = [
                cls._clean(entry.get("name"))
                for entry in contributors.get(field) or []
                if isinstance(entry, dict)
            ]
            present = [name for name in names if name]
            if present:
                return present
        return []

    @classmethod
    def _venue(cls, item: dict[str, Any]) -> str:
        """Return the journal, series or publisher a record appeared in."""
        source = item.get("source")
        if not isinstance(source, dict):
            return ""
        entries: list[object] = []
        for field in ("series", "book"):
            listed = source.get(field)
            if isinstance(listed, list):
                entries.extend(listed)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = cls._clean(
                entry.get("short_title") or entry.get("title") or entry.get("publisher")
            )
            if name:
                return name
        return ""

    @classmethod
    def _msc(cls, item: dict[str, Any]) -> list[str]:
        """Return the MSC classification codes of a record."""
        codes: list[str] = []
        for entry in item.get("msc") or []:
            if isinstance(entry, dict):
                code = cls._clean(entry.get("code"))
                if code:
                    codes.append(code)
        return codes

    @classmethod
    def _contribution(cls, item: dict[str, Any]) -> tuple[str, str]:
        """Return the ``(label, text)`` of a record's review or summary.

        The first non-placeholder contribution wins, so a record that carries
        both a review and an author summary is represented by its review.
        """
        for entry in item.get("editorial_contributions") or []:
            if not isinstance(entry, dict):
                continue
            text = cls._plain(entry.get("text"))
            if not text or _UNAVAILABLE_MARKER in text:
                continue
            kind = cls._clean(entry.get("contribution_type")).lower()
            label = "Review" if kind == "review" else "Summary"
            for prefix in ("Summary:", "Review:"):
                if text.startswith(prefix):
                    text = text[len(prefix) :].strip()
            return label, text
        return "", ""

    @classmethod
    def _link_identifier(cls, item: dict[str, Any], kind: str) -> str:
        """Return the identifier of the first link of *kind* (``doi``, ...)."""
        for entry in item.get("links") or []:
            if isinstance(entry, dict) and entry.get("type") == kind:
                identifier = cls._clean(entry.get("identifier"))
                if identifier:
                    return identifier
        return ""

    @classmethod
    def _language(cls, item: dict[str, Any]) -> str:
        """Return the record's main language, ignoring API placeholders."""
        language = item.get("language")
        if not isinstance(language, dict):
            return ""
        for entry in language.get("languages") or []:
            name = cls._clean(entry)
            if name and _UNAVAILABLE_MARKER not in name:
                return name
        return ""

    @classmethod
    def _score(
        cls,
        title: str,
        authors: list[str],
        normalized: str,
        tokens: list[str],
    ) -> int:
        """Rank a hit by title match quality, then by token coverage.

        Exact title matches outrank prefixes, which in turn outrank records
        that merely contain the query's tokens in their title or author list.
        """
        lowered = title.casefold()

        score = 0
        if lowered == normalized:
            score += 100
        elif lowered.startswith(normalized):
            score += 20
        score += 2 * sum(1 for token in tokens if token in lowered)
        joined = " ".join(authors).casefold()
        score += sum(1 for token in tokens if token in joined)
        return score

    def _snippet(
        self,
        authors: list[str],
        year: str,
        document_type: str,
        venue: str,
        zbl_number: str,
        msc: list[str],
        contribution: tuple[str, str],
    ) -> str:
        """Compose the snippet for a single record."""
        parts: list[str] = []
        if authors:
            listed = ", ".join(authors[:_SNIPPET_AUTHOR_LIMIT])
            if len(authors) > _SNIPPET_AUTHOR_LIMIT:
                listed += ", et al."
            parts.append(listed)
        if year:
            parts.append(year)
        if document_type:
            parts.append(document_type)
        if venue:
            parts.append(f"Source: {venue}")
        if zbl_number:
            parts.append(f"Zbl {zbl_number}")
        if msc:
            parts.append(f"MSC {', '.join(msc[:_SNIPPET_MSC_LIMIT])}")
        label, text = contribution
        if text:
            parts.append(f"{label}: {text[:_SNIPPET_REVIEW_LENGTH]}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(self, item: dict[str, Any]) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw zbMATH record."""
        title = self._title(item)
        if not title:
            return None

        authors = self._names(item)
        year = self._clean(item.get("year"))
        venue = self._venue(item)
        msc = self._msc(item)
        contribution = self._contribution(item)
        zbl_number = self._clean(item.get("identifier"))

        raw_type = item.get("document_type")
        document_type = ""
        if isinstance(raw_type, dict):
            document_type = self._clean(raw_type.get("description"))

        record_id = item.get("id")
        url = self._clean(item.get("zbmath_url"))
        if not url and isinstance(record_id, int):
            url = f"{_DOCUMENT_URL}{record_id}"

        return SearchResult(
            title=title,
            url=url,
            snippet=self._snippet(
                authors,
                year,
                document_type,
                venue,
                zbl_number,
                msc,
                contribution,
            ),
            source="zbmath.org",
            provider=self.name,
            published_date=year or None,
            extra={
                "zbl_number": zbl_number or None,
                "zbmath_id": record_id if isinstance(record_id, int) else None,
                "database": self._clean(item.get("database")) or None,
                "document_type": document_type or None,
                "authors": authors,
                "year": year or None,
                "source": venue or None,
                "msc": msc,
                "review": contribution[1] or None,
                "language": self._language(item) or None,
                "doi": self._link_identifier(item, "doi") or None,
                "arxiv_id": self._link_identifier(item, "arxiv") or None,
            },
        )

    def _parse(
        self,
        data: object,
        normalized: str,
        tokens: list[str],
        oversample: int,
    ) -> list[SearchResult]:
        """Parse a search response, deduplicating and ranking its hits."""
        if not isinstance(data, dict):
            return []
        entries = data.get("result")
        if not isinstance(entries, list):
            return []

        scored: list[tuple[int, SearchResult]] = []
        seen: set[object] = set()
        for item in entries:
            if len(scored) >= oversample:
                break
            if not isinstance(item, dict):
                continue
            # A record is keyed by its Zbl number, falling back to its id.
            key = self._clean(item.get("identifier")) or item.get("id")
            if key is not None and key in seen:
                continue
            if key is not None:
                seen.add(key)
            result = self._build_result(item)
            if result is None:
                continue
            authors = result.extra["authors"]
            scored.append(
                (self._score(result.title, authors, normalized, tokens), result),
            )

        # The sort is stable, so equally-relevant records keep the relevance
        # order the API returned them in.
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [result for _, result in scored]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search zbMATH Open for records matching *query*.

        The API answers ``404`` when a query matches nothing, which is
        reported as an empty page rather than as an error.  A blank query
        performs no request.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        oversample = min(limit * _RANK_OVERSAMPLE, _MAX_API_RESULTS)

        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={
                    "search_string": cleaned,
                    "results_per_page": str(oversample),
                    "page": "0",
                },
            )
            if resp.status_code == 404:
                # zbMATH reports a query without matches as a 404 with a null
                # result list.
                return ProviderResult(results=[])
            resp.raise_for_status()
            data = resp.json()

        normalized = cleaned.casefold()
        tokens = self._tokens(cleaned)
        results = self._parse(data, normalized, tokens, oversample)[:limit]
        for rank, result in enumerate(results, start=1):
            result.rank = rank
        return ProviderResult(results=results)
