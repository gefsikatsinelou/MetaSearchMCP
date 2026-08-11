"""Maven Central (Java/JVM) package search via the public Solr search API.

Maven Central is the default artifact repository for the Java and JVM
ecosystem. Its read-only Solr search endpoint requires no API key:

``GET https://search.maven.org/solrsearch/select?q=QUERY&rows=N&wt=json``

Each hit exposes the group/artifact coordinates, latest version,
packaging type, last-updated timestamp, and version count. Results link
to the artifact landing page on Sonatype Central.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://search.maven.org/solrsearch/select"
# Maven Central caps a single listing request at this many rows.
_MAX_API_RESULTS = 100


class MavenProvider(BaseProvider):
    """Search Java/JVM libraries published on Maven Central.

    Uses the keyless public Solr search API. Each result carries the Maven
    coordinates (groupId:artifactId), latest version, packaging type, and
    version count, linked to the Sonatype Central artifact page.
    """

    name = "maven"
    description = (
        "Search Java/JVM libraries and artifacts published on Maven Central, "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "packages"]

    @staticmethod
    def _artifact_url(group: str, artifact: str) -> str:
        """Return the Sonatype Central landing page for a Maven artifact."""
        return f"https://central.sonatype.com/artifact/{group}/{artifact}"

    @staticmethod
    def _timestamp_to_date(timestamp: object) -> str | None:
        """Convert a Maven epoch-millis timestamp to an ISO date string.

        Returns ``None`` when *timestamp* is missing or not a valid epoch
        millis value. Maven timestamps are milliseconds, unlike the seconds
        used by most other APIs, hence the ``/ 1000``.
        """
        if not timestamp:
            return None
        try:
            return (
                datetime.fromtimestamp(int(timestamp) / 1000, tz=UTC).date().isoformat()
            )
        except (TypeError, ValueError, OSError):
            return None

    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        """Parse the Maven Central Solr response into structured results."""
        results: list[SearchResult] = []
        docs = (data.get("response") or {}).get("docs") or []

        for i, doc in enumerate(docs, start=1):
            if not isinstance(doc, dict):
                continue
            group = doc.get("g") or ""
            artifact = doc.get("a") or ""
            if not group or not artifact:
                continue

            version = doc.get("latestVersion") or ""
            packaging = doc.get("p") or ""
            version_count = doc.get("versionCount") or 0

            snippet_parts: list[str] = []
            if version:
                snippet_parts.append(f"v{version}")
            if packaging:
                snippet_parts.append(f"Packaging: {packaging}")
            if version_count:
                snippet_parts.append(f"Versions: {version_count}")

            results.append(
                SearchResult(
                    title=f"{group}:{artifact}",
                    url=self._artifact_url(group, artifact),
                    snippet=" | ".join(snippet_parts),
                    source="Maven Central",
                    rank=i,
                    provider=self.name,
                    published_date=self._timestamp_to_date(doc.get("timestamp")),
                    extra={
                        "group": group,
                        "artifact": artifact,
                        "latest_version": version,
                        "packaging": packaging,
                        "version_count": version_count,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Maven Central for Java/JVM artifacts matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {"q": query, "rows": str(limit), "wt": "json"}
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)
