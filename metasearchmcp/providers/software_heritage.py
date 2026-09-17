"""Search the Software Heritage archive of public source code.

Software Heritage is the non-profit, universal archive of publicly available
source code: it has captured billions of files from tens of millions of
repository origins across GitHub, GitLab, Bitbucket, SourceForge, Debian,
PyPI, ... by repeatedly visiting and snapshotting them.  Its origin search
endpoint is public and keyless::

    GET https://archive.softwareheritage.org/api/1/origin/search/{pattern}/?limit=N

``pattern`` is matched against the origin URL (typically
``https://github.com/owner/repo``), so it doubles as repository discovery
across every hosting platform the archive has crawled — including ones with
no search API of their own.  The answer is a JSON array of origin records,
each carrying the repository URL, the visit types used to archive it
(``git``, ``svn``, ``hg``, ...), whether a snapshot was captured, the number
of visits, the date of the most recent visit, the snapshot identifier and
links to the visit and metadata endpoints.  The total number of matches is
exposed through the ``X-Total-Count`` response header.

This complements the live code and repository providers (GitHub, GitLab,
Codeberg, Sourcegraph) with an archival, platform-independent view of source
code.  No API key or registration is required.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote, urlsplit

import httpx

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://archive.softwareheritage.org/api/1/origin/search"
# Human-readable archive page for a given origin URL; the origin URL travels
# as a query parameter so it must be percent-encoded.
_BROWSE_URL = "https://archive.softwareheritage.org/browse/origin/?origin_url="
_SOURCE = "archive.softwareheritage.org"
# Keep requests modest to stay well inside the anonymous rate limit; the
# endpoint caps ``limit`` far below this, so it is only a safety net.
_MAX_API_RESULTS = 50


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


def _strings(value: object) -> list[str]:
    """Return the non-empty string entries of a list-valued field."""
    if not isinstance(value, (list, tuple)):
        return []
    return [text for entry in value if (text := _clean(entry))]


def _host(url: str) -> str:
    """Return the host of *url*, or an empty string when it has none."""
    return urlsplit(url).netloc


class SoftwareHeritageProvider(BaseProvider):
    """Search the Software Heritage archive of public source code.

    Keyless.  Queries the archive's origin search endpoint in a single
    request and returns one hit per matching repository origin, carrying its
    URL, archival visit types, snapshot availability, visit count, and the
    date it was last archived, plus a link to the record on
    ``archive.softwareheritage.org``.
    """

    name = "software_heritage"
    description = (
        "Search Software Heritage, the universal archive of public source "
        "code: repository origins (GitHub, GitLab, Bitbucket, ...) by URL "
        "keyword, with visit types, snapshot availability, visit counts and "
        "the last-archived date, plus a link to the archived record. "
        "No API key required."
    )
    tags: ClassVar[list[str]] = ["code", "developer", "repos", "archive"]

    @staticmethod
    def _title(url: str) -> str:
        """Return a readable label for an origin URL (scheme stripped)."""
        label = url.split("://", 1)[-1].rstrip("/")
        return label or url

    @staticmethod
    def _archive_url(url: str) -> str:
        """Return the archive page for an origin URL."""
        return f"{_BROWSE_URL}{quote(url, safe='')}"

    @staticmethod
    def _visit_types(item: dict[str, Any]) -> list[str]:
        """Return the VCS types the archive used to visit an origin."""
        return _strings(item.get("visit_types"))

    def _snippet(self, item: dict[str, Any], url: str) -> str:
        """Compose the snippet for a single archived origin.

        The snippet summarises the archival state: host, visit types, number
        of visits, and the date of the most recent visit, so that a result
        without a snapshot is still distinguishable from an actively
        archived one.
        """
        parts: list[str] = []
        host = _host(url)
        if host:
            parts.append(host)

        visit_types = self._visit_types(item)
        if visit_types:
            parts.append("Archived via " + ", ".join(visit_types))

        if item.get("has_visits") is False:
            parts.append("no snapshot captured")

        visits = _int(item.get("nb_visits"))
        if visits:
            parts.append(f"{visits} visit{'s' if visits != 1 else ''}")

        last_visit = _clean(item.get("last_visit_date"))
        if last_visit:
            parts.append(f"last visit {last_visit[:10]}")

        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        total: int | None,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a Software Heritage origin."""
        url = _clean(item.get("url"))
        if not url:
            return None

        archive_url = self._archive_url(url)
        last_visit = _clean(item.get("last_visit_date"))
        host = _host(url)

        return SearchResult(
            title=self._title(url),
            url=archive_url,
            snippet=self._snippet(item, url),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            published_date=last_visit[:10] or None,
            extra={
                "repository_url": url,
                "host": host or None,
                "archive_url": archive_url,
                "visit_types": self._visit_types(item),
                "has_visits": item.get("has_visits")
                if isinstance(item.get("has_visits"), bool)
                else None,
                "nb_visits": _int(item.get("nb_visits")),
                "snapshot_id": _clean(item.get("snapshot_id")) or None,
                "last_visit_date": last_visit or None,
                "total_results": total,
            },
        )

    def _parse(
        self,
        data: object,
        limit: int | None = None,
        total: int | None = None,
    ) -> ProviderResult:
        """Parse a Software Heritage origin search response.

        The endpoint answers with a JSON array of origin records in the
        archive's own relevance order, which is preserved; any other shape
        yields an empty page.
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
            built = self._build_result(item, total, len(results) + 1)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Software Heritage origins for *query*.

        A blank query performs no request.  The keyword is matched against
        repository URLs by the archive, and its relevance order is preserved
        in the returned results.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        # The keyword travels in the URL path, so slashes and other reserved
        # characters must be percent-encoded.
        url = f"{_SEARCH_URL}/{quote(cleaned, safe='')}/"

        async with self._client() as client:
            resp = await client.get(url, params={"limit": limit})
            # The endpoint answers 404 when nothing matches the pattern.
            if resp.status_code == 404:
                return ProviderResult(results=[])
            resp.raise_for_status()
            data: object = resp.json()
            total = self._header_int(resp, "x-total-count")

        return self._parse(data, limit, total)

    @staticmethod
    def _header_int(resp: httpx.Response, name: str) -> int | None:
        """Return an integer response header, or None when absent/invalid."""
        raw = resp.headers.get(name)
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None
