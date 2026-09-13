"""Chocolatey community package search via the keyless OData feed.

Chocolatey (community.chocolatey.org) is the package manager for Windows, and
its community gallery doubles as a NuGet-compatible OData v2 store.  The
gallery exposes an unauthenticated search endpoint::

    GET https://community.chocolatey.org/api/v2/Search()
        ?$filter=IsLatestVersion
        &searchTerm='QUERY'
        &targetFramework=''
        &includePrerelease=false
        &$top=N

The response is an Atom feed.  Each ``<entry>`` carries the package id in
``<title>`` and a ``<m:properties>`` block with the version, display title,
description, tags, download counts, project/license URLs, approval status and
publication timestamps.  Restricting the result set to ``IsLatestVersion``
reports only the newest stable release of each package, matching what
``choco install <id>`` resolves.

This complements the existing registry providers (npm, PyPI, NuGet, RubyGems,
AUR, ...), which cover the JS, Python, .NET, Ruby and Linux ecosystems but not
Windows.  No API key is required; parsing uses only the standard library.
"""

from __future__ import annotations

from typing import ClassVar
from xml.etree import ElementTree as ET

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://community.chocolatey.org/api/v2/Search()"
_PACKAGE_URL = "https://community.chocolatey.org/packages/"
# The gallery caps a single OData listing; keep pages small for agents.
_MAX_API_RESULTS = 30


def _local(tag: str) -> str:
    """Return the local part of an XML tag, ignoring any namespace prefix."""
    return tag.rsplit("}", 1)[-1]


class ChocolateyProvider(BaseProvider):
    """Search Chocolatey community packages for Windows.

    Keyless.  Queries the OData search feed for the latest stable version of
    each package matching the query.  Every hit carries the package id,
    version, description, tags, download counts and the gallery/project URLs.
    """

    name = "chocolatey"
    description = (
        "Search Chocolatey community packages for Windows (installable with "
        "`choco install`), no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "packages"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace/control characters in a free-text field."""
        if value is None:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _as_int(value: object) -> int | None:
        """Return *value* as an int, or ``None`` when it is not numeric."""
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    @classmethod
    def _date_prefix(cls, value: object) -> str | None:
        """Return the ``YYYY-MM-DD`` prefix of an OData timestamp, if any."""
        text = cls._clean(value)
        return text[:10] or None

    @staticmethod
    def _entry_fields(entry: ET.Element) -> dict[str, str]:
        """Index an entry's direct child elements by local tag name."""
        fields: dict[str, str] = {}
        for child in entry:
            name = _local(child.tag)
            if name not in fields:
                fields[name] = child.text or ""
        return fields

    @staticmethod
    def _properties(entry: ET.Element) -> dict[str, str]:
        """Index the NuGet-style ``<m:properties>`` block of an entry."""
        for child in entry.iter():
            if _local(child.tag) == "properties":
                return {_local(prop.tag): (prop.text or "") for prop in child}
        return {}

    @staticmethod
    def _author(entry: ET.Element) -> str:
        """Return the package author name from an entry's ``<author>`` block."""
        for child in entry:
            if _local(child.tag) != "author":
                continue
            for node in child:
                if _local(node.tag) == "name":
                    return " ".join((node.text or "").split())
        return ""

    def _snippet(self, summary: str, version: str, downloads: int | None) -> str:
        """Compose the snippet for a single package entry."""
        parts: list[str] = []
        if summary:
            parts.append(summary)
        if version:
            parts.append(f"v{version}")
        if downloads:
            parts.append(f"Downloads: {downloads:,}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build(self, entry: ET.Element, rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a gallery entry."""
        fields = self._entry_fields(entry)
        props = self._properties(entry)
        package_id = self._clean(fields.get("title")) or self._clean(
            props.get("Title"),
        )
        if not package_id:
            return None

        version = self._clean(props.get("Version"))
        title = self._clean(props.get("Title")) or package_id
        summary = self._clean(fields.get("summary")) or self._clean(
            props.get("Description"),
        )
        downloads = self._as_int(props.get("DownloadCount"))
        tags = self._clean(props.get("Tags")).split()
        url = self._clean(props.get("GalleryDetailsUrl")) or (
            f"{_PACKAGE_URL}{package_id}"
        )
        published = self._date_prefix(props.get("Published") or fields.get("updated"))
        status = self._clean(props.get("PackageStatus"))
        dependencies = [
            part.strip()
            for part in self._clean(props.get("Dependencies")).split("|")
            if part.strip()
        ]

        return SearchResult(
            title=title,
            url=url,
            snippet=self._snippet(summary, version, downloads),
            source="chocolatey.org",
            rank=rank,
            provider=self.name,
            published_date=published,
            extra={
                "package_id": package_id,
                "version": version,
                "authors": self._author(entry) or None,
                "tags": tags,
                "total_downloads": downloads,
                "version_downloads": self._as_int(
                    props.get("VersionDownloadCount"),
                ),
                "is_prerelease": self._clean(props.get("IsPrerelease")).lower()
                == "true",
                "is_latest_version": self._clean(props.get("IsLatestVersion")).lower()
                == "true",
                "package_status": status or None,
                "project_url": self._clean(props.get("ProjectUrl")) or None,
                "license_url": self._clean(props.get("LicenseUrl")) or None,
                "dependencies": dependencies,
                "published_date": published,
            },
        )

    def _parse(self, xml_text: str, limit: int) -> ProviderResult:
        """Parse an OData/Atom search feed into structured results."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return ProviderResult(results=[])

        results: list[SearchResult] = []
        for entry in root.iter():
            if _local(entry.tag) != "entry":
                continue
            result = self._build(entry, len(results) + 1)
            if result is None:
                continue
            results.append(result)
            if len(results) >= limit:
                break
        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the Chocolatey community gallery for *query*.

        Only the latest stable version of each matching package is returned.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        query_params = {
            "$filter": "IsLatestVersion",
            "searchTerm": f"'{cleaned}'",
            "targetFramework": "''",
            "includePrerelease": "false",
            "$top": str(limit),
        }
        async with self._client() as client:
            resp = await client.get(_SEARCH_URL, params=query_params)
            resp.raise_for_status()
            xml_text = resp.text

        return self._parse(xml_text, limit)
