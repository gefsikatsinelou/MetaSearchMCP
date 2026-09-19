"""Search peer-reviewed AI/ML submissions on OpenReview.

OpenReview is the public review platform behind ICLR, NeurIPS, ICML, COLM and
many workshops and journals.  Its v2 API exposes a keyless full-text search over
every note it stores::

    GET https://api2.openreview.net/notes/search
        ?query=<query>&limit=N&offset=0&source=forum

``source=forum`` restricts the search to top-level submissions, so the reviews
and comments that also contain the query terms never reach the result set.  Each
forum carries the paper's title, authors, abstract, keywords, the venue it was
submitted to together with its current status (*Submitted to ICLR 2024*,
*ICLR 2024 Oral*, ...), its primary area, an optional TLDR and links to both the
discussion page and the PDF.

This complements the purely bibliographic providers (arXiv, DBLP, Semantic
Scholar, OpenAlex) with the machine-learning community's peer-review record: it
surfaces recent submissions that are not indexed elsewhere yet, and it adds the
venue and decision metadata bibliographic databases usually omit.  No API key is
required.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_ENDPOINT = "https://api2.openreview.net/notes/search"
_SOURCE = "openreview.net"
# Human-readable discussion page of a submission (its "forum" note).
_FORUM_URL = "https://openreview.net/forum?id={identifier}"
# Direct link to the submission PDF.
_PDF_URL = "https://openreview.net/pdf?id={identifier}"
# The API serves up to a few hundred notes per request; a search only ever asks
# for ``num_results`` (capped at 50) so this is a defensive upper bound.
_MAX_API_RESULTS = 100
# Longest TLDR or abstract quoted in a snippet.
_MAX_SNIPPET_SUMMARY = 200
# Number of authors listed in a snippet.
_MAX_SNIPPET_AUTHORS = 3
# Number of keywords quoted in a snippet.
_MAX_SNIPPET_KEYWORDS = 4
# Content fields whose (string) value is used as a fallback title.
_TITLE_FIELDS = ("title", "TLDR")


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _int(value: object) -> int | None:
    """Return an integer field, ignoring booleans and non-integer values."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _field(content: dict[str, Any], key: str) -> object:
    """Return the value of an OpenReview content field.

    OpenReview wraps every field in a ``{"value": ...}`` object; plain values
    are returned unchanged so that hand-written payloads still parse.
    """
    entry = content.get(key)
    if isinstance(entry, dict):
        return entry.get("value")
    return entry


def _text(content: dict[str, Any], key: str) -> str:
    """Return a single-line string content field."""
    return _clean(_field(content, key))


def _text_list(content: dict[str, Any], key: str) -> list[str]:
    """Return the non-empty string entries of a list-valued content field.

    Some notes store a single string instead of a list; those are wrapped so
    that callers always receive a list.
    """
    value = _field(content, key)
    if isinstance(value, str):
        cleaned = _clean(value)
        return [cleaned] if cleaned else []
    if not isinstance(value, (list, tuple)):
        return []
    return [text for entry in value if (text := _clean(entry))]


def _truncate(value: str, limit: int) -> str:
    """Shorten *value* to *limit* characters, appending an ellipsis."""
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _date(value: object) -> str | None:
    """Convert a millisecond epoch timestamp into a ``YYYY-MM-DD`` date."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    try:
        moment = datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return moment.date().isoformat()


def _title(content: dict[str, Any]) -> str:
    """Return a submission's readable title.

    Submissions always carry a ``title``; the TLDR is used as a fallback for the
    rare note that only exposes a summary.
    """
    for field in _TITLE_FIELDS:
        title = _text(content, field)
        if title:
            return title
    return ""


def _authors_line(authors: list[str]) -> str:
    """Join the first few authors, marking any remainder with *et al.*"""
    if not authors:
        return ""
    shown = authors[:_MAX_SNIPPET_AUTHORS]
    if len(authors) > _MAX_SNIPPET_AUTHORS:
        return ", ".join(shown) + " et al."
    return ", ".join(shown)


class OpenReviewProvider(BaseProvider):
    """Search OpenReview submissions across ML conferences and workshops.

    Keyless.  *query* is matched against the titles, abstracts, keywords and
    reviews of every submission on OpenReview; only top-level submissions are
    returned, and each hit links to its discussion page and carries the venue,
    status, authors and keywords.
    """

    name = "openreview"
    description = (
        "Search OpenReview, the public peer-review platform of ICLR, NeurIPS, "
        "ICML, COLM and many workshops: submissions with title, authors, "
        "abstract, keywords, venue, review status, primary area, TLDR and PDF "
        "links. No API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "preprints", "ai"]

    def _snippet(
        self,
        content: dict[str, Any],
        authors: list[str],
        venue: str,
        keywords: list[str],
    ) -> str:
        """Compose the snippet for a single submission.

        The TLDR (or, failing that, the abstract) comes first, followed by the
        authors, the venue and a few keywords so that a result stays informative
        without reading ``extra``.
        """
        parts: list[str] = []

        summary = _text(content, "TLDR") or _text(content, "abstract")
        if summary:
            parts.append(_truncate(summary, _MAX_SNIPPET_SUMMARY))

        authors_line = _authors_line(authors)
        if authors_line:
            parts.append(authors_line)

        if venue:
            parts.append(venue)

        if keywords:
            parts.append(", ".join(keywords[:_MAX_SNIPPET_KEYWORDS]))

        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        note: dict[str, Any],
        total: int | None,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from an OpenReview forum note."""
        content = note.get("content")
        if not isinstance(content, dict):
            return None

        identifier = _clean(note.get("id")) or _clean(note.get("forum"))
        title = _title(content)
        if not identifier or not title:
            return None

        authors = _text_list(content, "authors")
        keywords = _text_list(content, "keywords")
        venue = _text(content, "venue")
        url = _FORUM_URL.format(identifier=identifier)

        return SearchResult(
            title=title,
            url=url,
            snippet=self._snippet(content, authors, venue, keywords),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            published_date=_date(note.get("cdate")),
            extra={
                "forum": _clean(note.get("forum")) or identifier,
                "forum_url": url,
                "pdf_url": _PDF_URL.format(identifier=identifier),
                "authors": authors,
                "venue": venue or None,
                "venueid": _text(content, "venueid") or None,
                "primary_area": _text(content, "primary_area") or None,
                "keywords": keywords,
                "tldr": _text(content, "TLDR") or None,
                "abstract": _text(content, "abstract") or None,
                "number": _int(note.get("number")),
                "domain": _clean(note.get("domain")) or None,
                "license": _clean(note.get("license")) or None,
                "version": _int(note.get("version")),
                "created": _date(note.get("cdate")),
                "total_results": total,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse an OpenReview search response into structured results.

        OpenReview's own relevance order is preserved and duplicate versions of
        the same submission (same ``forum`` id) are collapsed onto their first
        occurrence.  Any other payload shape yields an empty result set.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        notes = data.get("notes")
        if not isinstance(notes, list):
            return ProviderResult(results=results)

        total = _int(data.get("count"))
        max_results = self._max_results if limit is None else limit
        seen: set[str] = set()
        for note in notes:
            if len(results) >= max_results:
                break
            if not isinstance(note, dict):
                continue
            key = _clean(note.get("forum")) or _clean(note.get("id"))
            if key and key in seen:
                continue
            built = self._build_result(note, total, len(results) + 1)
            if built is None:
                continue
            if key:
                seen.add(key)
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search OpenReview submissions for *query*.

        A blank query performs no request.  A single page is fetched, sized to
        ``num_results`` and limited to forums so that reviews and comments never
        appear as hits.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        if limit <= 0:
            return ProviderResult(results=[])

        async with self._client() as client:
            resp = await client.get(
                _ENDPOINT,
                params={
                    "query": cleaned,
                    "limit": limit,
                    "offset": 0,
                    "source": "forum",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit)
