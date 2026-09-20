"""Search the J-STAGE platform of Japanese scholarly journals.

J-STAGE (``www.jstage.jst.go.jp``) is the Japan Science and Technology Agency's
open platform for Japanese academic society journals: several thousand titles,
from the physical and life sciences to engineering, medicine, the humanities
and the social sciences, are published there directly by their learned
societies.  A large share of that literature — conference proceedings, society
journals, technical reports — never reaches the Western bibliographic
databases, so the platform complements arXiv, Crossref, OpenAlex and the other
academic providers with the Japanese scholarly record.

Its Web API is public and keyless::

    GET https://api.jstage.jst.go.jp/searchapi/do
        ?service=3&article=<query>&count=N&start=0

``service=3`` selects the article-search service and ``article=`` matches the
query against article titles.  The response is an Atom feed whose entries carry
the English and Japanese title, the authors in both scripts, the journal name,
its ISSN, volume/number/pages, the publication year and the DOI, so a result
stays informative without any follow-up request.

No API key or registration is required.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://api.jstage.jst.go.jp/searchapi/do"
_SOURCE = "jstage.jst.go.jp"
# Fallback link for records that carry neither a landing URL nor a DOI.
_SEARCH_PAGE = "https://www.jstage.jst.go.jp/"
_DOI_URL = "https://doi.org/"
# ``service=3`` is the Web API's article-search service.
_SERVICE = "3"
# J-STAGE accepts up to 1000 records per request; a search never asks for more
# than ``num_results`` (capped at 50), so this is a defensive upper bound.
_MAX_API_RESULTS = 100
# Number of authors listed in a snippet.
_MAX_SNIPPET_AUTHORS = 3

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "prism": "http://prismstandard.org/namespaces/basic/2.0/",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _int(value: object) -> int | None:
    """Return an integer field, ignoring booleans and non-numeric values."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _text(element: ET.Element | None, path: str) -> str:
    """Return the whitespace-collapsed text of *path* below *element*."""
    if element is None:
        return ""
    return _clean(element.findtext(path, None, _NS))


def _localized(element: ET.Element | None) -> str:
    """Return the English rendering of a bilingual element, else the Japanese.

    J-STAGE duplicates most metadata in an ``<en>`` and a ``<ja>`` child; the
    Japanese text is only used when the English one is missing, and a plain
    (non-bilingual) element is read directly.
    """
    if element is None:
        return ""
    for language in ("en", "ja"):
        child = element.find(f"atom:{language}", _NS)
        if child is not None and (text := _clean(child.text)):
            return text
    return _clean(element.text)


def _authors(entry: ET.Element) -> list[str]:
    """Return the authors of an entry, preferring their Latin-script names."""
    author = entry.find("atom:author", _NS)
    if author is None:
        return []
    for language in ("en", "ja"):
        script = author.find(f"atom:{language}", _NS)
        if script is None:
            continue
        names = [
            text
            for node in script.findall("atom:name", _NS)
            if (text := _clean(node.text))
        ]
        if names:
            return names
    return []


def _pages(entry: ET.Element) -> str:
    """Return the page range of an entry, e.g. ``113-120``."""
    start = _text(entry, "prism:startingPage")
    end = _text(entry, "prism:endingPage")
    if start and end and start != end:
        return f"{start}-{end}"
    return start or end


def _article_url(entry: ET.Element, doi: str) -> str:
    """Return the best available link for an article.

    The English J-STAGE article page is preferred, then the Atom ``link``
    element, then a ``doi.org`` resolver URL, and finally the platform home
    page so that a result always carries a link.
    """
    url = _localized(entry.find("atom:article_link", _NS))
    if url:
        return url
    link = entry.find("atom:link", _NS)
    if link is not None and (href := _clean(link.get("href"))):
        return href
    if doi:
        return f"{_DOI_URL}{doi}"
    return _SEARCH_PAGE


class JStageProvider(BaseProvider):
    """Search Japanese scholarly articles published on J-STAGE.

    Keyless.  *query* is matched against article titles, and each hit carries
    the authors, the journal and its ISSN, the volume/number/pages, the
    publication year and the DOI of the matching article.
    """

    name = "jstage"
    description = (
        "Search J-STAGE, Japan's scholarly journal platform: articles by "
        "title, with the English and Japanese title, authors, journal, ISSN, "
        "volume/number/pages, publication year and DOI. No API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "web", "science"]

    def _snippet(
        self,
        authors: list[str],
        journal: str,
        volume: str,
        number: str,
        pages: str,
        year: str,
    ) -> str:
        """Compose the snippet for a single article.

        Authors, the journal, its volume/number, the page range and the
        publication year are combined so that a hit stays informative without
        reading ``extra``.
        """
        parts: list[str] = []

        if authors:
            listed = ", ".join(authors[:_MAX_SNIPPET_AUTHORS])
            if len(authors) > _MAX_SNIPPET_AUTHORS:
                listed += " et al."
            parts.append(listed)

        if journal:
            parts.append(journal)

        if volume:
            citation = f"Vol. {volume}"
            if number:
                citation += f", No. {number}"
            parts.append(citation)
        elif number:
            parts.append(f"No. {number}")

        if pages:
            parts.append(f"pp. {pages}")

        if year:
            parts.append(year)

        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        entry: ET.Element,
        total: int | None,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a J-STAGE feed entry."""
        title = _localized(entry.find("atom:article_title", _NS)) or _text(
            entry,
            "atom:title",
        )
        if not title:
            return None

        doi = _text(entry, "prism:doi")
        authors = _authors(entry)
        journal = _localized(entry.find("atom:material_title", _NS))
        volume = _text(entry, "prism:volume")
        number = _text(entry, "prism:number")
        pages = _pages(entry)
        year = _text(entry, "atom:pubyear")
        updated = _text(entry, "atom:updated")

        # ``<pubyear>`` is the publication year, while Atom's ``<updated>`` is
        # only the record's last-modified stamp, so the year is preferred and
        # the timestamp is used as a fallback date.
        published = year or self._iso_date_prefix(updated)

        return SearchResult(
            title=title,
            url=_article_url(entry, doi),
            snippet=self._snippet(authors, journal, volume, number, pages, year),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            published_date=published,
            extra={
                "doi": doi or None,
                "authors": authors,
                "journal": journal or None,
                "cdjournal": _text(entry, "atom:cdjournal") or None,
                "issn": _text(entry, "prism:issn") or None,
                "eissn": _text(entry, "prism:eIssn") or None,
                "volume": volume or None,
                "number": number or None,
                "pages": pages or None,
                "pubyear": _int(year),
                "system_name": _text(entry, "atom:systemname") or None,
                "updated": updated or None,
                "total_results": total,
            },
        )

    def _parse(self, xml_text: object, limit: int | None = None) -> ProviderResult:
        """Parse a J-STAGE Atom feed into structured results.

        J-STAGE's own relevance order is preserved.  Protocol-level failures
        (an ``ERR_`` status element, malformed XML, a non-XML payload) all
        yield an empty result set rather than an exception.
        """
        results: list[SearchResult] = []
        if not isinstance(xml_text, (str, bytes)):
            return ProviderResult(results=results)

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return ProviderResult(results=results)

        if _text(root, "atom:result/atom:status").upper().startswith("ERR"):
            return ProviderResult(results=results)

        total = _int(root.findtext("opensearch:totalResults", None, _NS))
        max_results = self._max_results if limit is None else limit
        for entry in root.findall("atom:entry", _NS):
            if len(results) >= max_results:
                break
            built = self._build_result(entry, total, len(results) + 1)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search J-STAGE articles for *query*.

        A blank query performs no request.  The keyword is matched against the
        article titles of every journal hosted on J-STAGE, and J-STAGE's own
        relevance order is preserved in the results.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        if limit <= 0:
            return ProviderResult(results=[])

        async with self._client() as client:
            resp = await client.get(
                _SEARCH_URL,
                params={
                    "service": _SERVICE,
                    "article": cleaned,
                    "count": limit,
                    "start": 0,
                },
            )
            resp.raise_for_status()
            xml_text = resp.text

        return self._parse(xml_text, limit)
