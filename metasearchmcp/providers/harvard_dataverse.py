"""Search research datasets deposited in Harvard Dataverse.

Harvard Dataverse (``dataverse.harvard.edu``) is the largest installation of
the open-source Dataverse repository platform, hosting hundreds of thousands
of research datasets — survey and replication data, social-science and
biomedical data, codebooks and supplementary files — contributed by
researchers worldwide.  Its search API is public and keyless::

    GET https://dataverse.harvard.edu/api/search
        ?q=<query>&type=dataset&per_page=N&start=0

The response carries ``data.total_count`` and one ``data.items`` record per
matching dataset, and each record already holds everything a search hit needs:
the dataset title, its DOI, the description, the authors, the publication
date, the dataverse it belongs to, its subject classifications, the number of
files and the version state.  No per-record follow-up request is required,
so the provider complements DataCite, Figshare, Zenodo, Dryad and the OSF
preprint provider with the Dataverse research-data ecosystem.

No API key or registration is required.
"""

from __future__ import annotations

import html
import re
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://dataverse.harvard.edu/api/search"
# Fallback link for records that carry neither a landing URL nor a DOI.
_SEARCH_PAGE = "https://dataverse.harvard.edu/"
_DOI_URL = "https://doi.org/"
_SOURCE = "dataverse.harvard.edu"
# Dataverse accepts large page sizes; the orchestrator never asks for more.
_MAX_API_RESULTS = 100
# Descriptions are long free-text blobs; keep a readable prefix in ``extra``.
_MAX_DESCRIPTION_LENGTH = 300
# Number of authors / subjects listed in a snippet.
_MAX_SNIPPET_LIST = 3
# Only datasets are queried, so stray dataverse/file hits never appear.
_RESULT_TYPE = "dataset"

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
    """Return the non-empty cleaned strings of a JSON list field."""
    if not isinstance(value, (list, tuple)):
        return []
    return [text for entry in value if (text := _clean(entry))]


def _contacts(value: object) -> list[dict[str, str]]:
    """Return the name/affiliation pairs of a dataset's contact persons."""
    if not isinstance(value, (list, tuple)):
        return []
    people: list[dict[str, str]] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        name = _clean(entry.get("name"))
        if not name:
            continue
        person = {"name": name}
        affiliation = _clean(entry.get("affiliation"))
        if affiliation:
            person["affiliation"] = affiliation
        people.append(person)
    return people


class HarvardDataverseProvider(BaseProvider):
    """Search research datasets hosted on Harvard Dataverse.

    Keyless.  A single request returns one hit per matching dataset, carrying
    its authors, description, DOI, publication date, publisher dataverse,
    subject classification, file count and version.  Hits link to the dataset
    DOI or, when the record has no identifier, to the repository home page.
    """

    name = "harvard_dataverse"
    description = (
        "Search Harvard Dataverse, the largest open research data repository: "
        "datasets by keyword, with authors, description, DOI, publication "
        "date, subject classification, file count and version. No API key "
        "required."
    )
    tags: ClassVar[list[str]] = ["academic", "data", "datasets", "repositories"]

    @staticmethod
    def _dataset_url(item: dict[str, Any], global_id: str, doi: str) -> str:
        """Return the best available link for a dataset record.

        The API-provided URL (usually a DOI resolver link) is preferred, then
        a ``doi.org`` link built from a DOI-shaped global identifier, and
        finally the repository home page so that a result always carries a
        link.
        """
        url = _clean(item.get("url"))
        if url:
            return url
        if global_id[:4].lower() == "doi:":
            return f"{_DOI_URL}{doi}"
        return _SEARCH_PAGE

    @staticmethod
    def _version(item: dict[str, Any]) -> str:
        """Return the ``major.minor`` version label of a dataset record."""
        major = _int(item.get("majorVersion"))
        if major is None:
            return ""
        minor = _int(item.get("minorVersion"))
        return f"{major}.{minor if minor is not None else 0}"

    def _snippet(
        self,
        authors: list[str],
        item: dict[str, Any],
        subjects: list[str],
        file_count: int | None,
        description: str,
    ) -> str:
        """Compose the snippet for a single dataset.

        Authors, publication date, publisher dataverse, subjects and file
        count are combined so that a hit stays informative without reading
        ``extra``.  A record carrying none of those fields falls back to its
        description, global identifier or type so the snippet is rarely empty.
        """
        parts: list[str] = []
        if authors:
            listed = ", ".join(authors[:_MAX_SNIPPET_LIST])
            if len(authors) > _MAX_SNIPPET_LIST:
                listed += " et al."
            parts.append(listed)

        published = self._iso_date_prefix(_clean(item.get("published_at")))
        if published:
            parts.append(published)

        publisher = _clean(item.get("publisher"))
        if publisher:
            parts.append(publisher)

        if subjects:
            parts.append(", ".join(subjects[:_MAX_SNIPPET_LIST]))

        if file_count is not None:
            parts.append(f"{file_count} file{'s' if file_count != 1 else ''}")

        if not parts:
            fallback = (
                description[:_MAX_DESCRIPTION_LENGTH]
                or _clean(item.get("global_id"))
                or _clean(item.get("type"))
            )
            if fallback:
                parts.append(fallback)

        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        total: int | None,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a Dataverse dataset record."""
        title = _clean(item.get("name"))
        if not title:
            return None

        global_id = _clean(item.get("global_id"))
        doi = global_id[4:].strip() if global_id[:4].lower() == "doi:" else global_id

        authors = _strings(item.get("authors"))
        subjects = _strings(item.get("subjects"))
        description = _text(item.get("description"))
        file_count = _int(item.get("fileCount"))
        version = self._version(item)

        return SearchResult(
            title=title,
            url=self._dataset_url(item, global_id, doi),
            snippet=self._snippet(
                authors,
                item,
                subjects,
                file_count,
                description,
            ),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            published_date=self._iso_date_prefix(_clean(item.get("published_at"))),
            extra={
                "doi": doi or None,
                "global_id": global_id or None,
                "authors": authors,
                "description": description[:_MAX_DESCRIPTION_LENGTH] or None,
                "publisher": _clean(item.get("publisher")) or None,
                "dataverse": _clean(item.get("name_of_dataverse")) or None,
                "dataverse_alias": _clean(item.get("identifier_of_dataverse")) or None,
                "subjects": subjects,
                "file_count": file_count,
                "version": version or None,
                "version_state": _clean(item.get("versionState")) or None,
                "publication_statuses": _strings(item.get("publicationStatuses")),
                "contacts": _contacts(item.get("contacts")),
                "created_at": _clean(item.get("createdAt")) or None,
                "updated_at": _clean(item.get("updatedAt")) or None,
                "total_results": total,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a Dataverse search response into structured results.

        Dataverse's own relevance order is preserved, and any payload that is
        not a successful search response yields an empty result set.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict) or data.get("status") != "OK":
            return ProviderResult(results=results)

        payload = data.get("data")
        if not isinstance(payload, dict):
            return ProviderResult(results=results)

        items = payload.get("items")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        total = _int(payload.get("total_count"))
        max_results = self._max_results if limit is None else limit
        for item in items:
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
        """Search Harvard Dataverse for datasets matching *query*.

        A blank query performs no request.  The keyword is matched against the
        datasets' titles, descriptions, authors, keywords and field values,
        and Dataverse's relevance order is preserved in the results.
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
                    "q": cleaned,
                    "type": _RESULT_TYPE,
                    "per_page": limit,
                    "start": 0,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit)
