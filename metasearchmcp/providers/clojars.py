"""Clojars (Clojure) package search via the public JSON search API.

Clojars is the community artifact repository for the Clojure ecosystem.
Its read-only search endpoint requires no API key and can return JSON::

    GET https://clojars.org/search?q=QUERY&format=json

Each hit exposes the artifact coordinates (``group_name``/``jar_name``),
the latest version, a free-text description, and the creation timestamp.
Results link to the artifact landing page on ``clojars.org``.

A common shorthand on Clojars is ``group/jar`` (e.g. ``clj-http/clj-http``),
which this provider mirrors when building the title and URL.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://clojars.org/search"
_SITE_BASE = "https://clojars.org"
_SOURCE = "Clojars"
# Clojars returns at most this many hits per page by default.
_MAX_API_RESULTS = 24


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field, returning ``""`` for empties."""
    if value is None:
        return ""
    return " ".join(str(value).split())


class ClojarsProvider(BaseProvider):
    """Search Clojure libraries and artifacts published on Clojars.

    Uses the keyless JSON search API. Each result carries the artifact
    coordinates (a qualified ``group/jar`` name), the latest version, and
    the description, linked to the artifact page on ``clojars.org``.
    """

    name = "clojars"
    description = (
        "Search Clojure libraries and artifacts published on Clojars, "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "packages"]

    @staticmethod
    def _artifact_url(group: str, artifact: str) -> str:
        """Return the Clojars landing page for a qualified artifact name."""
        return f"{_SITE_BASE}/{group}/{artifact}"

    @staticmethod
    def _timestamp_to_date(timestamp: object) -> str | None:
        """Convert a Clojars epoch-millis timestamp to an ISO date string.

        Returns ``None`` when *timestamp* is missing or not a valid epoch
        millis value. Clojars timestamps are milliseconds, hence the
        ``/ 1000``.
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
        """Parse the Clojars JSON response into structured results."""
        results: list[SearchResult] = []
        hits = data.get("results")
        if not isinstance(hits, list):
            return ProviderResult(results=results)

        for i, hit in enumerate(hits, start=1):
            if not isinstance(hit, dict):
                continue
            group = _clean(hit.get("group_name"))
            artifact = _clean(hit.get("jar_name"))
            if not group or not artifact:
                continue

            version = _clean(hit.get("version"))
            description = _clean(hit.get("description"))

            snippet_parts: list[str] = []
            if description:
                snippet_parts.append(description)
            if version:
                snippet_parts.append(f"v{version}")

            results.append(
                SearchResult(
                    title=f"{group}/{artifact}",
                    url=self._artifact_url(group, artifact),
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source=_SOURCE,
                    rank=i,
                    provider=self.name,
                    published_date=self._timestamp_to_date(hit.get("created")),
                    extra={
                        "group": group,
                        "artifact": artifact,
                        "latest_version": version,
                        "description": description,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Clojars for Clojure artifacts matching *query*."""
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {"q": cleaned, "format": "json"}
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        result = self._parse(data)
        result.results = result.results[:limit]
        return result
