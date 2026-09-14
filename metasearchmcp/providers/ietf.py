"""IETF Datatracker document search (RFCs and Internet-Drafts).

The IETF Datatracker (datatracker.ietf.org) is the authoritative index of the
Internet standards process: published RFCs together with the Internet-Drafts
that are working their way towards publication.  It exposes a read-only,
keyless REST API over the document collection::

    GET https://datatracker.ietf.org/api/v1/doc/document/
        ?title__icontains=QUERY&type__slug__in=rfc,draft&format=json&limit=N
    GET https://datatracker.ietf.org/api/v1/doc/document/
        ?abstract__icontains=QUERY&type__slug__in=rfc,draft&format=json&limit=N

Both calls return JSON.  A hit carries the document name (``rfc9221`` or
``draft-ietf-quic-datagram``), its title, abstract, document type, standards
level, stream, page count, keywords and expiry date; enumerations are encoded
as URIs (``/api/v1/name/stdlevelname/ps/``), so only the trailing slug is kept.

The two filters are queried separately because the API combines multiple
filters with AND.  Title matches are surfaced first and abstract-only matches
only fill the remaining slots, which mirrors how standards are usually looked
up: by name first, then by topic.  Note that the API's ``time`` field is the
record's last modification time, not the publication date, so it is reported
under ``extra["updated"]`` rather than as ``published_date``.

This complements the code- and package-registry providers with the standards
documents themselves.  No API key is required.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://datatracker.ietf.org/api/v1/doc/document/"
_DOC_PAGE_URL = "https://datatracker.ietf.org/doc/"

# Datatracker also stores meeting slides and similar artefacts under the same
# endpoint; only real standards documents are indexed here.
_DOC_TYPE_SLUGS = "rfc,draft"
_INDEXED_DOC_TYPES = frozenset({"rfc", "draft"})

# The API paginates its listings; keep pages small for agents.
_MAX_API_RESULTS = 30
# Oversample hits so that local re-ranking still fills a full page.
_RANK_OVERSAMPLE = 2
# Characters of the abstract copied into the snippet.
_SNIPPET_ABSTRACT_LENGTH = 180
# Keywords surfaced in a snippet before truncation.
_SNIPPET_KEYWORD_LIMIT = 5

_STD_LEVEL_LABELS: dict[str, str] = {
    "ps": "Proposed Standard",
    "std": "Internet Standard",
    "ds": "Draft Standard",
    "bcp": "Best Current Practice",
    "inf": "Informational",
    "exp": "Experimental",
    "hist": "Historic",
    "unkn": "Unknown status",
}

_STREAM_LABELS: dict[str, str] = {
    "ietf": "IETF",
    "irtf": "IRTF",
    "iab": "IAB",
    "ise": "Independent Submission",
    "editorial": "Editorial",
    "legacy": "Legacy",
}

_WORD_RE = re.compile(r"[a-z0-9]+")


class IetfProvider(BaseProvider):
    """Search IETF RFCs and Internet-Drafts.

    Keyless.  Queries the Datatracker document API for title and abstract
    matches concurrently, keeps title matches first and deduplicates the two
    sets by document name.  Each hit carries the document name, type,
    standards level, stream, page count and abstract, and links to the
    document's Datatracker page.
    """

    name = "ietf"
    description = (
        "Search IETF RFCs and Internet-Drafts (titles and abstracts) via the "
        "keyless Datatracker API — Internet standards and working-group "
        "drafts with standards level and page count."
    )
    tags: ClassVar[list[str]] = ["web", "developer", "standards", "reference"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _int(value: object) -> int:
        """Return *value* as an integer, ignoring booleans and non-integers."""
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return 0

    @staticmethod
    def _code(value: object) -> str:
        """Return the trailing slug of a Datatracker URI-valued field.

        Enumerations arrive as URIs such as ``/api/v1/name/stdlevelname/ps/``,
        where the slug (``ps``) is the actual value.
        """
        if not isinstance(value, str):
            return ""
        return value.rstrip("/").rsplit("/", 1)[-1].strip()

    @staticmethod
    def _tokens(query: str) -> list[str]:
        """Return the lowercase alphanumeric tokens of *query*."""
        return _WORD_RE.findall(query.lower())

    @classmethod
    def _title_score(cls, title: str, tokens: list[str]) -> int:
        """Count how many query *tokens* appear in *title*."""
        lowered = title.lower()
        return sum(1 for token in tokens if token in lowered)

    @classmethod
    def _keywords(cls, value: object) -> list[str]:
        """Parse the API's stringified keyword list into plain strings.

        Datatracker serialises keywords as a Python-style list literal
        (``"['quic', 'transport']"``) rather than as a JSON array.
        """
        if not isinstance(value, str):
            return []
        keywords: list[str] = []
        for part in value.strip().strip("[]").split(","):
            keyword = cls._clean(part.strip().strip("'\""))
            if keyword:
                keywords.append(keyword)
        return keywords

    @staticmethod
    def _snippet(
        label: str,
        std_level: str,
        stream: str,
        pages: int,
        keywords: list[str],
        abstract: str,
    ) -> str:
        """Compose the snippet for a single document."""
        parts: list[str] = [label]
        if std_level:
            parts.append(std_level)
        if stream:
            parts.append(stream)
        if pages:
            parts.append(f"{pages} pages")
        if keywords:
            parts.append(f"Keywords: {', '.join(keywords[:_SNIPPET_KEYWORD_LIMIT])}")
        if abstract:
            parts.append(abstract[:_SNIPPET_ABSTRACT_LENGTH])
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    @classmethod
    def _label(cls, doc_type: str, rfc: str, name: str) -> str:
        """Return the human-readable document label used in snippets."""
        if doc_type == "rfc" and rfc:
            return f"RFC {rfc}"
        return f"Internet-Draft {name}"

    def _build_result(self, item: dict[str, Any]) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw Datatracker document."""
        name = self._clean(item.get("name"))
        doc_type = self._code(item.get("type"))
        if not name or doc_type not in _INDEXED_DOC_TYPES:
            return None

        rfc = self._clean(item.get("rfc"))
        std_level = self._code(item.get("std_level"))
        stream = self._code(item.get("stream"))
        keywords = self._keywords(item.get("keywords"))
        pages = self._int(item.get("pages"))
        title = self._clean(item.get("title")) or name

        return SearchResult(
            title=title,
            url=f"{_DOC_PAGE_URL}{quote(name)}/",
            snippet=self._snippet(
                self._label(doc_type, rfc, name),
                _STD_LEVEL_LABELS.get(std_level, std_level.upper()),
                _STREAM_LABELS.get(stream, stream.upper()),
                pages,
                keywords,
                self._clean(item.get("abstract")),
            ),
            source="datatracker.ietf.org",
            provider=self.name,
            extra={
                "doc_name": name,
                "kind": "rfc" if doc_type == "rfc" else "draft",
                "rfc_number": self._int(item.get("rfc_number")) or None,
                "std_level": std_level or None,
                "stream": stream or None,
                "pages": pages or None,
                "keywords": keywords,
                "expires": self._iso_date_prefix(
                    self._clean(item.get("expires")) or None,
                ),
                "updated": self._iso_date_prefix(
                    self._clean(item.get("time")) or None,
                ),
            },
        )

    @staticmethod
    def _entries(data: object) -> list[dict[str, Any]]:
        """Return the document objects of a Datatracker list response."""
        if not isinstance(data, dict):
            return []
        objects = data.get("objects")
        if not isinstance(objects, list):
            return []
        return [item for item in objects if isinstance(item, dict)]

    def _parse(
        self,
        data: object,
        tokens: list[str],
        limit: int,
    ) -> list[SearchResult]:
        """Parse a document list response, ranking title matches first."""
        scored: list[tuple[int, SearchResult]] = []
        for item in self._entries(data):
            if len(scored) >= limit:
                break
            result = self._build_result(item)
            if result is None:
                continue
            scored.append((self._title_score(result.title, tokens), result))

        # The sort is stable, so equally-relevant documents keep the order the
        # API returned them in.
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [result for _, result in scored]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the IETF Datatracker for documents matching *query*.

        Titles and abstracts are queried concurrently; title matches lead the
        page and abstract-only matches fill the remaining slots.  A failure on
        one filter degrades gracefully to the other, and only an error from
        both is raised.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        oversample = min(limit * _RANK_OVERSAMPLE, _MAX_API_RESULTS)

        async def _fetch(field: str) -> object:
            async with self._client() as client:
                resp = await client.get(
                    _API_URL,
                    params={
                        field: cleaned,
                        "type__slug__in": _DOC_TYPE_SLUGS,
                        "format": "json",
                        "limit": str(oversample),
                    },
                )
                resp.raise_for_status()
                return resp.json()

        payloads = await asyncio.gather(
            _fetch("title__icontains"),
            _fetch("abstract__icontains"),
            return_exceptions=True,
        )
        failures = [p for p in payloads if isinstance(p, Exception)]
        if len(failures) == len(payloads):
            raise failures[0]

        tokens = self._tokens(cleaned)
        merged = self._parse(payloads[0], tokens, oversample)
        seen = {result.extra["doc_name"] for result in merged}
        for result in self._parse(payloads[1], tokens, oversample):
            name = result.extra["doc_name"]
            if name in seen:
                continue
            seen.add(name)
            merged.append(result)
            if len(merged) >= limit:
                break

        results = merged[:limit]
        for rank, result in enumerate(results, start=1):
            result.rank = rank
        return ProviderResult(results=results)
