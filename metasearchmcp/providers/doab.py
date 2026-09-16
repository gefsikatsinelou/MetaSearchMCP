"""DOAB open-access book search via the public, keyless REST API.

DOAB (Directory of Open Access Books, doabooks.org) is the book-side companion
of DOAJ: it indexes peer-reviewed, openly licensed scholarly books and
monographs from hundreds of publishers, and it is harvested by OAPEN,
OpenEdition, JSTOR Open Access and many university presses.  Every record
carries its title (and any alternative/subtitle), authors and editors, the
publisher and imprint, the year of issue, ISBN, DOI, language, licence, series,
subject headings and an abstract.

The search endpoint is public and keyless::

    GET https://directory.doabooks.org/rest/search?query=QUERY&limit=N

The response is a plain JSON list of DSpace items, each with a ``handle`` and a
``metadata`` list of ``{"key": ..., "value": ...}`` entries.  The endpoint also
indexes non-book entities (grantors, publishers), so the query is narrowed with
the Solr ``dc.type:book`` filter and each hit is checked before it is reported.
The total number of matching books is returned in the ``X-Total-Count``
response header.

This complements DOAJ (articles), Open Library and Project Gutenberg
(public-domain trade books) by answering which scholarly books on a topic are
free to read and download right now.  No API key is required.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://directory.doabooks.org/rest/search"
# Public landing page of a book, keyed by its DSpace handle.
_HANDLE_URL = "https://directory.doabooks.org/handle/"
# Solr filter that keeps the search to book records only.
_BOOK_TYPE_FILTER = "dc.type:book"
# DOAB serves up to 100 records per page.
_MAX_API_RESULTS = 100
# Characters with meaning in Solr syntax, stripped from the user's query.
_SOLR_SPECIAL = re.compile(r'[:"()\[\]{}^~*?\\/|!]')
# Characters copied from an abstract into the snippet.
_SNIPPET_ABSTRACT_LENGTH = 180
# Authors, editors and subject headings listed in a snippet.
_SNIPPET_AUTHOR_LIMIT = 5
_SNIPPET_SUBJECT_LIMIT = 3
# ISBNs embedded in ONIX identifier strings, e.g. ``ONIX_20241025_978..._16``.
_ISBN = re.compile(r"97[89]\d{10}")
# Leading four-digit year of a ``dc.date.issued`` value.
_YEAR = re.compile(r"\d{4}")


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


class DoabProvider(BaseProvider):
    """Search DOAB for peer-reviewed open-access scholarly books.

    Keyless.  Queries the DOAB REST API and returns one hit per book, carrying
    its authors or editors, publisher, year, ISBN, DOI, language, licence,
    series and subject headings, and linking to the DOI or the DOAB landing
    page.  Only book records are reported.
    """

    name = "doab"
    description = (
        "Search DOAB (Directory of Open Access Books) — peer-reviewed, openly "
        "licensed scholarly books and monographs (title, authors, publisher, "
        "year, ISBN, DOI, subjects, abstract) via the keyless REST API."
    )
    tags: ClassVar[list[str]] = ["academic", "books", "knowledge", "web"]

    @staticmethod
    def _solr_query(query: str) -> str:
        """Return *query* with the characters that are special to Solr removed.

        The user's words are passed through as a Solr query so that the
        ``dc.type:book`` filter can be appended; punctuation that carries
        meaning to Solr is dropped rather than interpreted.
        """
        return " ".join(_SOLR_SPECIAL.sub(" ", query).split())

    @staticmethod
    def _metadata(entry: object) -> dict[str, list[str]]:
        """Group an item's Dublin Core metadata by key.

        DSpace reports metadata as a list of ``{"key": ..., "value": ...}``
        entries, a key repeating once per value.  Values that are not
        plain strings (structured or empty values) are skipped.
        """
        fields: dict[str, list[str]] = {}
        if not isinstance(entry, dict):
            return fields
        for item in entry.get("metadata") or []:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            value = item.get("value")
            if not isinstance(key, str) or not key:
                continue
            if isinstance(value, str):
                text = _clean(value)
            elif value is None or isinstance(value, (dict, list)):
                continue
            else:
                text = _clean(value)
            if text:
                fields.setdefault(key, []).append(text)
        return fields

    @staticmethod
    def _first(fields: dict[str, list[str]], key: str) -> str:
        """Return the first value of a metadata key, or an empty string."""
        values = fields.get(key)
        return values[0] if values else ""

    @staticmethod
    def _values(fields: dict[str, list[str]], key: str, limit: int = 0) -> list[str]:
        """Return the distinct values of a metadata key, optionally capped."""
        values: list[str] = []
        for value in fields.get(key, []):
            if value not in values:
                values.append(value)
            if limit and len(values) >= limit:
                break
        return values

    @staticmethod
    def _year(value: str) -> str:
        """Return the four-digit year of a ``dc.date.issued`` value."""
        match = _YEAR.search(value)
        return match.group(0) if match else ""

    @staticmethod
    def _isbn(fields: dict[str, list[str]]) -> list[str]:
        """Return the ISBNs of a book, including ones inside ONIX identifiers."""
        isbns = DoabProvider._values(fields, "dc.identifier.isbn")
        for value in fields.get("dc.identifier", []):
            match = _ISBN.search(value)
            if match and match.group(0) not in isbns:
                isbns.append(match.group(0))
        return isbns

    @staticmethod
    def _subjects(fields: dict[str, list[str]]) -> list[str]:
        """Return the book's subject headings, without the noisy classifications.

        DOAB stores free-text keywords next to ``thema EDItEUR::<scheme path>``
        classification strings; only the readable keywords are kept.
        """
        return [
            subject
            for subject in DoabProvider._values(fields, "dc.subject.other")
            if "::" not in subject and not subject.startswith("thema ")
        ]

    @classmethod
    def _book_url(cls, fields: dict[str, list[str]], handle: str) -> str:
        """Return the best landing-page URL for a book."""
        doi = cls._first(fields, "oapen.identifier.doi")
        if doi:
            return f"https://doi.org/{doi}"
        url = cls._first(fields, "dc.identifier.uri")
        if url.startswith("http"):
            return url
        return f"{_HANDLE_URL}{quote(handle)}" if handle else ""

    @staticmethod
    def _snippet(
        abstract: str,
        publisher: str,
        year: str,
        authors: list[str],
        editors: list[str],
        subjects: list[str],
        language: str,
        series: str,
    ) -> str:
        """Compose the snippet for a single book."""
        parts: list[str] = []
        if abstract:
            parts.append(abstract[:_SNIPPET_ABSTRACT_LENGTH])
        if authors:
            parts.append(f"Authors: {', '.join(authors)}")
        if editors:
            parts.append(f"Editors: {', '.join(editors)}")
        if publisher:
            parts.append(f"Publisher: {publisher}")
        if year:
            parts.append(f"Year: {year}")
        if series:
            parts.append(f"Series: {series}")
        if subjects:
            parts.append(f"Subjects: {', '.join(subjects)}")
        if language:
            parts.append(f"Language: {language}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        entry: object,
        rank: int,
        total: int | None,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a DOAB item."""
        fields = self._metadata(entry)
        handle = _clean(entry.get("handle")) if isinstance(entry, dict) else ""
        title = _clean(self._first(fields, "dc.title"))
        if not title and isinstance(entry, dict):
            title = _clean(entry.get("name"))
        if not title:
            return None

        types = self._values(fields, "dc.type")
        # The Solr filter normally guarantees books; report only book records.
        if types and not any("book" in value.lower() for value in types):
            return None

        url = self._book_url(fields, handle)
        if not url:
            return None

        authors = self._values(fields, "dc.contributor.author", _SNIPPET_AUTHOR_LIMIT)
        editors = self._values(fields, "dc.contributor.editor", _SNIPPET_AUTHOR_LIMIT)
        subjects = self._subjects(fields)[:_SNIPPET_SUBJECT_LIMIT]
        publisher = self._first(fields, "dc.publisher") or self._first(
            fields,
            "publisher.name",
        )
        year = self._year(self._first(fields, "dc.date.issued"))
        language = self._first(fields, "dc.language")
        series = self._first(fields, "dc.relation.ispartofseries")
        license_name = self._first(fields, "dc.rights")
        doi = self._first(fields, "oapen.identifier.doi")
        isbns = self._isbn(fields)
        abstract = self._first(fields, "dc.description.abstract")

        return SearchResult(
            title=title,
            url=url,
            snippet=self._snippet(
                abstract,
                publisher,
                year,
                authors,
                editors,
                subjects,
                language,
                series,
            ),
            source="doabooks.org",
            rank=rank,
            provider=self.name,
            published_date=year or None,
            extra={
                "doi": doi,
                "isbn": isbns,
                "authors": authors,
                "editors": editors,
                "publisher": publisher,
                "year": year,
                "language": language,
                "license": license_name,
                "series": series,
                "subjects": self._subjects(fields),
                "alternative_title": self._first(fields, "dc.title.alternative"),
                "handle": handle,
                "abstract": abstract,
                "total_results": total,
            },
        )

    def _parse(
        self,
        data: object,
        limit: int,
        total: int | None = None,
    ) -> ProviderResult:
        """Parse the DOAB API response into structured search results."""
        if not isinstance(data, list):
            return ProviderResult(results=[])

        results: list[SearchResult] = []
        for entry in data:
            built = self._build_result(entry, len(results) + 1, total)
            if built is None:
                continue
            results.append(built)
            if len(results) >= limit:
                break

        return ProviderResult(results=results)

    @staticmethod
    def _total(headers: Any) -> int | None:
        """Return the number of matching books reported in the response header."""
        try:
            raw = headers.get("x-total-count")
        except (AttributeError, TypeError):
            return None
        if raw is None:
            return None
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return None

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search DOAB for open-access books matching *query*.

        A blank query -- or one made only of Solr punctuation -- performs no
        request.  The portal's relevance ranking is preserved.
        """
        cleaned = self._solr_query(query.strip())
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {
            "query": f"{cleaned} AND {_BOOK_TYPE_FILTER}",
            "limit": str(limit),
            "expand": "metadata",
        }

        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data: object = resp.json()
            total = self._total(resp.headers)

        return self._parse(data, limit, total)
