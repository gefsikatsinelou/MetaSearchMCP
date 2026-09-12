"""HAL Open Science scholarly search via the public, keyless REST API.

HAL (hal.science) is the French national open-access repository, operated by
CCSD/CNRS.  It indexes several million scholarly records deposited by
universities, research organisations and authors — journal articles,
conference papers, preprints, theses, book chapters, reports and patents —
the majority of them in French or English.  The search endpoint is keyless:

``GET https://api.archives-ouvertes.fr/search/?q=QUERY&wt=json&rows=N&fl=...``

Results use Solr's format: every document is a flat dict whose keys carry a
type suffix (``title_s`` for a string/list, ``producedDateY_i`` for an int),
so all values are coerced defensively.  This complements
:mod:`metasearchmcp.providers.openalex` and
:mod:`metasearchmcp.providers.openaire` by querying the French national
repository directly — including the French-language metadata those
aggregators often collapse into a single English record.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.archives-ouvertes.fr/search/"
# Fields requested from the Solr backend, keeping the payload agent-friendly.
_FIELDS = (
    "title_s,authFullName_s,producedDate_s,producedDateY_i,uri_s,abstract_s,"
    "docType_s,language_s,doiId_s,journalTitle_s,keyword_s,halId_s,citationRef_s"
)
# HAL accepts large pages; keep them small because results are for agents.
_MAX_API_RESULTS = 50
# Number of author names shown inline before falling back to "et al.".
_MAX_DISPLAY_AUTHORS = 3
# Number of keywords shown in a result snippet.
_MAX_KEYWORDS_IN_SNIPPET = 5

# Precompiled pattern for stripping the HTML that HAL embeds in fields such as
# ``citationRef_s`` (which wraps the citation in ``<i>``/``<a>`` tags).
_TAG_RE = re.compile(r"<[^>]+>")
# Matches a complete ISO calendar date; HAL dates are sometimes only YYYY-MM.
_FULL_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Friendly labels for the most common HAL document-type codes.
_DOC_TYPE_LABELS: dict[str, str] = {
    "ART": "journal article",
    "ARTREV": "review article",
    "COMM": "conference paper",
    "POSTER": "conference poster",
    "PROCEEDINGS": "proceedings",
    "ISSUE": "special issue",
    "OUV": "book",
    "COUV": "book chapter",
    "THESE": "thesis",
    "HDR": "habilitation thesis",
    "MEMOIRE": "master's thesis",
    "PREPRINT": "preprint",
    "UNDEFINED": "preprint",
    "WORKINGPAPER": "working paper",
    "REPORT": "report",
    "PATENT": "patent",
    "TRAD": "translation",
    "NOTICE": "encyclopedia entry",
    "BLOG": "blog post",
    "OTHER": "publication",
}


def _string_list(value: object) -> list[str]:
    """Coerce a Solr field that may be a string or list into a list of strings."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _clean(value: object) -> str:
    """Collapse whitespace in *value* and strip any embedded HTML tags."""
    if value is None:
        return ""
    text = _TAG_RE.sub(" ", str(value))
    return " ".join(text.split())


class HalProvider(BaseProvider):
    """Search scholarly records deposited in the HAL open-access repository.

    Keyless.  Uses the public HAL search API (Solr backend) across all
    disciplines and languages.  Each result carries the title, authors,
    institution/journal, document type, language, keywords, DOI, HAL id and
    the abstract when available.
    """

    name = "hal"
    description = (
        "Search scholarly records (articles, preprints, theses, book chapters) "
        "deposited in the HAL national open-access repository — no API key "
        "required."
    )
    tags: ClassVar[list[str]] = ["academic", "web"]

    @staticmethod
    def _title(doc: dict[str, Any]) -> str:
        """Return the first non-empty title variant of a HAL document."""
        for candidate in _string_list(doc.get("title_s")):
            cleaned = _clean(candidate)
            if cleaned:
                return cleaned
        return ""

    @staticmethod
    def _authors(doc: dict[str, Any]) -> list[str]:
        """Return the deduplicated, cleaned author names of a document."""
        authors: list[str] = []
        seen: set[str] = set()
        for raw in _string_list(doc.get("authFullName_s")):
            name = _clean(raw)
            if name and name not in seen:
                seen.add(name)
                authors.append(name)
        return authors

    @staticmethod
    def _published_date(doc: dict[str, Any]) -> str | None:
        """Return a full ISO date for the document, or ``None``.

        HAL often stores only a year or year-month, in which case no
        ``published_date`` is emitted (the raw value stays in ``extra``).
        """
        produced = _clean(doc.get("producedDate_s"))
        return produced if _FULL_DATE_RE.match(produced) else None

    @staticmethod
    def _doc_type_label(code: str) -> str:
        """Map a HAL document-type code to a friendly English label."""
        if not code:
            return ""
        return _DOC_TYPE_LABELS.get(code, code.lower())

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse the HAL Solr JSON response into structured search results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        response = data.get("response")
        if not isinstance(response, dict):
            return ProviderResult(results=results)
        docs = response.get("docs")
        if not isinstance(docs, list):
            return ProviderResult(results=results)

        total = response.get("numFound")
        max_results = limit or self._max_results

        for doc in docs:
            if not isinstance(doc, dict):
                continue

            title = self._title(doc)
            url = _clean(doc.get("uri_s"))
            if not title or not url.startswith(("http://", "https://")):
                continue

            authors = self._authors(doc)
            display_authors = authors[:_MAX_DISPLAY_AUTHORS]
            if len(authors) > _MAX_DISPLAY_AUTHORS:
                display_authors = [*display_authors, "et al."]

            abstract_values = _string_list(doc.get("abstract_s"))
            abstract = _clean(abstract_values[0]) if abstract_values else ""

            journal = _clean(doc.get("journalTitle_s"))
            doi = _clean(doc.get("doiId_s"))
            hal_id = _clean(doc.get("halId_s"))
            languages = [_clean(lang) for lang in _string_list(doc.get("language_s"))]
            language = languages[0] if languages else ""
            keywords = [
                _clean(word)
                for word in _string_list(doc.get("keyword_s"))
                if _clean(word)
            ]
            doc_type = _clean(doc.get("docType_s"))
            doc_type_label = self._doc_type_label(doc_type)
            produced_date = _clean(doc.get("producedDate_s"))
            raw_year = doc.get("producedDateY_i")
            year = raw_year if isinstance(raw_year, int) else None
            citation = _clean(doc.get("citationRef_s"))

            snippet_parts: list[str] = []
            if abstract:
                snippet_parts.append(abstract)
            if journal:
                snippet_parts.append(journal)
            if display_authors:
                snippet_parts.append(", ".join(display_authors))
            if doc_type_label:
                snippet_parts.append(f"Type: {doc_type_label}")
            if keywords:
                snippet_parts.append(
                    f"Keywords: {', '.join(keywords[:_MAX_KEYWORDS_IN_SNIPPET])}",
                )
            if not abstract and citation:
                snippet_parts.append(citation)

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source="hal.science",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=self._published_date(doc),
                    extra={
                        "doi": doi,
                        "hal_id": hal_id,
                        "authors": authors,
                        "journal_title": journal,
                        "doc_type": doc_type,
                        "doc_type_label": doc_type_label,
                        "language": language,
                        "keywords": keywords,
                        "year": year,
                        "produced_date": produced_date,
                        "total_results": total,
                    },
                ),
            )
            if len(results) >= max_results:
                break

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search HAL for scholarly records matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        request_params = {
            "q": query,
            "wt": "json",
            "rows": str(limit),
            "start": "0",
            "fl": _FIELDS,
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=request_params)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
