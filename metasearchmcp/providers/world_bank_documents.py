"""Search the World Bank's Documents & Reports repository of development research.

The World Bank's Documents & Reports portal (``documents.worldbank.org``)
publishes the institution's open knowledge output: well over half a million
publications, working papers, policy research reports, project appraisal and
completion documents, country economic memoranda and official loan/grant
agreements.  Its search endpoint is public and keyless::

    GET https://search.worldbank.org/api/v2/wds?format=json&qterm=QUERY&rows=N

``qterm`` is a free-text query matched against document titles, abstracts and
metadata.  The answer is an object carrying the total number of matches plus a
``documents`` mapping of document id to record (with a ``facets`` entry that is
not a document).  Each record carries the document name (``docna``, nested one
level deep), its type (Publication, Working Paper, Project Appraisal Document,
...), the publication date, the language, the report number, the associated
project and country, an abstract under ``abstracts``, and links to the document
landing page plus its PDF and plain-text renderings.

This complements the scholarly providers (OpenAlex, Crossref, DOAJ, ...) with
the grey literature and operational documents that World Bank research
produces, and the open-data providers (data.europa.eu) with a document-level
search.  No API key or registration is required.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://search.worldbank.org/api/v2/wds"
# Human-readable document landing page, keyed by the document's GUID.
_DOCUMENT_URL = (
    "https://documents.worldbank.org/en/publication/documents-reports/documentdetail/"
)
# Portal home page, used when a record carries no usable document identifier.
_HOME_URL = "https://documents.worldbank.org/"
_SOURCE = "documents.worldbank.org"
# Fields requested per record; without this list the endpoint answers with very
# large records carrying every facet and full text of each document.
_FIELDS = ",".join(
    (
        "docna",
        "display_title",
        "docdt",
        "count",
        "docty",
        "projn",
        "repnb",
        "lang",
        "guid",
        "url",
        "pdfurl",
        "txturl",
        "abstracts",
    )
)
# The endpoint rounds small ``rows`` values up (it answers with more documents
# than requested), so results are always sliced to the limit after parsing.
_MAX_API_RESULTS = 50


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _string(value: object) -> str:
    """Return a plain string field, or an empty string."""
    return value if isinstance(value, str) else ""


def _int(value: object) -> int | None:
    """Return an integer field, ignoring booleans and non-integer values."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _nested_text(value: object) -> str:
    """Return the first non-empty text found in a nested API field.

    Fields such as ``docna`` and ``abstracts`` arrive wrapped in extra mappings
    — ``{"0": {"docna": "..."}}`` and ``{"cdata!": "..."}`` — so this walks
    whatever nesting the endpoint returns.
    """
    if isinstance(value, str):
        return _clean(value)
    if isinstance(value, dict):
        entries: object = value.values()
    elif isinstance(value, (list, tuple)):
        entries = value
    else:
        return ""
    for entry in entries:
        text = _nested_text(entry)
        if text:
            return text
    return ""


class WorldBankDocumentsProvider(BaseProvider):
    """Search the World Bank's Documents & Reports repository.

    Keyless.  Queries the World Bank document search API in a single request
    and returns one hit per matching document, carrying its title, document
    type, publication date, language, report number, project and country, an
    abstract, and a link to the record on ``documents.worldbank.org``.
    """

    name = "worldbank_documents"
    description = (
        "Search the World Bank's Documents & Reports repository — 500,000+ "
        "development publications, working papers, project documents and "
        "country reports — by keyword, returning each document's title, type, "
        "date, language, project and country plus a link to the record. "
        "No API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "data", "gov", "reference"]

    @staticmethod
    def _title(item: dict[str, Any]) -> str:
        """Return a document's display title, falling back to its name."""
        return _clean(item.get("display_title")) or _nested_text(item.get("docna"))

    @staticmethod
    def _abstract(item: dict[str, Any]) -> str:
        """Return a document's abstract, or an empty string when absent."""
        return _nested_text(item.get("abstracts"))

    @staticmethod
    def _url(item: dict[str, Any]) -> str:
        """Return the best available link to a document's landing page."""
        for key in ("url", "url_friendly_title"):
            link = _string(item.get(key))
            if link:
                return link
        identifier = _string(item.get("guid")) or _string(item.get("id"))
        return f"{_DOCUMENT_URL}{identifier}" if identifier else _HOME_URL

    @staticmethod
    def _snippet(
        abstract: str,
        document_type: str,
        project: str,
        country: str,
        report_number: str,
        language: str,
    ) -> str:
        """Compose the snippet for a single document.

        The abstract is preferred; records without one fall back to a compact
        summary of their catalogue metadata.
        """
        if abstract:
            return abstract[:MAX_SNIPPET_LENGTH]
        parts: list[str] = []
        if document_type:
            parts.append(f"Type: {document_type}")
        if project:
            parts.append(f"Project: {project}")
        if country:
            parts.append(f"Country: {country}")
        if report_number:
            parts.append(f"Report: {report_number}")
        if language:
            parts.append(f"Language: {language}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        total: int | None,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a World Bank document record."""
        title = self._title(item)
        if not title:
            return None

        abstract = self._abstract(item)
        document_type = _clean(item.get("docty"))
        project = _clean(item.get("projn"))
        country = _clean(item.get("count"))
        report_number = _clean(item.get("repnb"))
        language = _clean(item.get("lang"))
        url = self._url(item)

        return SearchResult(
            title=title,
            url=url,
            snippet=self._snippet(
                abstract,
                document_type,
                project,
                country,
                report_number,
                language,
            ),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            published_date=self._iso_date_prefix(_string(item.get("docdt"))),
            extra={
                "id": _string(item.get("id")) or None,
                "guid": _string(item.get("guid")) or None,
                "document_type": document_type or None,
                "language": language or None,
                "report_number": report_number or None,
                "project": project or None,
                "country": country or None,
                "pdf_url": _string(item.get("pdfurl")) or None,
                "text_url": _string(item.get("txturl")) or None,
                "total_results": total,
                "url": url,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a World Bank document search response into structured results.

        The endpoint answers with an object carrying a ``documents`` mapping of
        document id to record; any other shape yields an empty page.  Mapping
        order is the repository's own relevance order, so it is preserved.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        documents = data.get("documents")
        if not isinstance(documents, dict):
            return ProviderResult(results=results)

        total = _int(data.get("total"))
        max_results = limit or self._max_results
        for key, item in documents.items():
            if len(results) >= max_results:
                break
            # ``facets`` rides along in the same mapping but is not a document.
            if key == "facets" or not isinstance(item, dict):
                continue
            built = self._build_result(item, total, len(results) + 1)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search World Bank documents for *query*.

        A blank query performs no request.  The repository's relevance order is
        preserved in the returned results; the endpoint returns slightly more
        documents than requested, so the response is sliced to the limit.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        async with self._client() as client:
            resp = await client.get(
                _SEARCH_URL,
                params={
                    "format": "json",
                    "qterm": cleaned,
                    "rows": limit,
                    "os": 0,
                    "fl": _FIELDS,
                },
            )
            resp.raise_for_status()
            data: object = resp.json()

        return self._parse(data, limit)
