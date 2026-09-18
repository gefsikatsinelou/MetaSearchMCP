"""Search the Dryad curated open-access research data repository.

Dryad is a non-profit repository where researchers deposit the data that
underlies published papers, and where every dataset is curated and released
under an open licence.  Its search endpoint is public and keyless::

    GET https://datadryad.org/api/v2/search?q=<query>&per_page=N

The response is JSON:API flavoured: ``total`` carries the number of matching
datasets and ``_embedded["stash:datasets"]`` the current page of dataset
records.  Each record already carries a rich metadata bundle — title,
authors (with affiliations and ORCIDs), abstract, keywords, field of
science, methods, funder awards, licence, version, publication date, usage
metrics and the dataset DOI — so, like the Zenodo and Figshare providers, no
per-record follow-up request is needed.  Every result links to the dataset
landing page on ``datadryad.org`` and exposes both the DOI and the API
download endpoint for the underlying files.

No API key or registration is required.
"""

from __future__ import annotations

import html
import re
from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://datadryad.org/api/v2/search"
# Base for the public dataset landing page; the DOI-like identifier is
# appended verbatim (e.g. ``doi:10.5061/dryad.8kprr4z23``).
_DATASET_URL = "https://datadryad.org/dataset/"
# API endpoint that streams the dataset files as a zip archive.
_DATASET_API_URL = "https://datadryad.org/api/v2/datasets/"
_SOURCE = "datadryad.org"
# Dryad's search endpoint caps ``per_page`` at 100.
_MAX_API_RESULTS = 100
# Abstracts are long HTML blobs; keep only a readable prefix in ``extra``.
_MAX_ABSTRACT_LENGTH = 500

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _text(value: object) -> str:
    """Return a whitespace-collapsed, tag-free rendering of an HTML field."""
    raw = _clean(value)
    if not raw:
        return ""
    return " ".join(html.unescape(_TAG_RE.sub(" ", raw)).split())


def _int(value: object) -> int | None:
    """Return an integer field, ignoring booleans and non-integer values."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _strings(value: object) -> list[str]:
    """Return the non-empty string entries of a list-valued field."""
    if not isinstance(value, (list, tuple)):
        return []
    return [text for entry in value if (text := _clean(entry))]


def _authors(value: object) -> list[str]:
    """Return the display names of a dataset's authors, in listed order."""
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        name = " ".join(
            part
            for part in (_clean(entry.get("firstName")), _clean(entry.get("lastName")))
            if part
        )
        if name:
            names.append(name)
    return names


class DryadProvider(BaseProvider):
    """Search datasets deposited in the Dryad research data repository.

    Keyless.  Queries the Dryad search endpoint in a single request and
    returns one hit per matching dataset, carrying its authors, abstract,
    keywords, field of science, licence, version, usage metrics and DOI,
    plus links to the landing page and the file download endpoint.
    """

    name = "dryad"
    description = (
        "Search Dryad, the curated open-access repository of research data "
        "behind published papers: datasets by keyword, with authors, "
        "abstract, keywords, field of science, licence, version, usage "
        "metrics and the dataset DOI. No API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "data", "datasets", "repositories"]

    @staticmethod
    def _landing_url(item: dict[str, Any], identifier: str) -> str:
        """Return the best available URL for a dataset record.

        The identifier is the canonical form; the API-provided sharing link
        is only a fallback for records that lack one.
        """
        if identifier:
            return f"{_DATASET_URL}{identifier}"
        return _clean(item.get("sharingLink")).replace("http://", "https://", 1)

    @staticmethod
    def _download_url(identifier: str) -> str:
        """Return the API download endpoint for a dataset identifier."""
        if not identifier:
            return ""
        return f"{_DATASET_API_URL}{quote(identifier, safe='')}/download"

    @staticmethod
    def _metrics(item: dict[str, Any]) -> dict[str, int]:
        """Return the non-empty usage metrics of a dataset record."""
        raw = item.get("metrics")
        if not isinstance(raw, dict):
            return {}
        metrics: dict[str, int] = {}
        for key in ("views", "downloads", "citations"):
            value = _int(raw.get(key))
            if value is not None:
                metrics[key] = value
        return metrics

    def _snippet(
        self,
        authors: list[str],
        item: dict[str, Any],
        metrics: dict[str, int],
    ) -> str:
        """Compose the snippet for a single dataset.

        Author list, publication year, field of science, keywords and
        download count are combined so that a result is informative even
        when the caller does not look at ``extra``.
        """
        parts: list[str] = []
        if authors:
            listed = ", ".join(authors[:3])
            if len(authors) > 3:
                listed += " et al."
            parts.append(listed)

        published = _clean(item.get("publicationDate"))
        if published:
            parts.append(published)

        field = _clean(item.get("fieldOfScience"))
        if field:
            parts.append(field)

        keywords = _strings(item.get("keywords"))
        if keywords:
            parts.append(", ".join(keywords[:5]))

        downloads = metrics.get("downloads")
        if downloads is not None:
            parts.append(f"{downloads} download{'s' if downloads != 1 else ''}")

        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        total: int | None,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a Dryad dataset record."""
        title = _clean(item.get("title"))
        if not title:
            return None

        identifier = _clean(item.get("identifier"))
        authors = _authors(item.get("authors"))
        metrics = self._metrics(item)
        abstract = _text(item.get("abstract"))[:_MAX_ABSTRACT_LENGTH]

        return SearchResult(
            title=title,
            url=self._landing_url(item, identifier),
            snippet=self._snippet(authors, item, metrics),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            published_date=_clean(item.get("publicationDate")) or None,
            extra={
                "doi": identifier,
                "authors": authors,
                "abstract": abstract or None,
                "keywords": _strings(item.get("keywords")),
                "field_of_science": _clean(item.get("fieldOfScience")) or None,
                "license": _clean(item.get("license")) or None,
                "version_number": _int(item.get("versionNumber")),
                "version_status": _clean(item.get("versionStatus")) or None,
                "curation_status": _clean(item.get("curationStatus")) or None,
                "storage_size": _int(item.get("storageSize")),
                "metrics": metrics or None,
                "related_publication_issn": _clean(item.get("relatedPublicationISSN"))
                or None,
                "download_url": self._download_url(identifier) or None,
                "total_results": total,
            },
        )

    def _parse(
        self,
        data: object,
        limit: int | None = None,
    ) -> ProviderResult:
        """Parse a Dryad search response into structured results.

        Records arrive in the repository's own relevance order, which is
        preserved; any other payload shape yields an empty page.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        embedded = data.get("_embedded")
        datasets = (
            embedded.get("stash:datasets") if isinstance(embedded, dict) else None
        )
        if not isinstance(datasets, list):
            return ProviderResult(results=results)

        total = _int(data.get("total"))
        max_results = limit or self._max_results
        for item in datasets:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            built = self._build_result(item, total, len(results) + 1)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Dryad datasets for *query*.

        A blank query performs no request.  The keyword is matched by Dryad
        against dataset titles, abstracts, keywords and methods, and its
        relevance order is preserved in the returned results.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _SEARCH_URL,
                params={"q": cleaned, "per_page": limit},
            )
            resp.raise_for_status()
            data: object = resp.json()

        return self._parse(data, limit)
