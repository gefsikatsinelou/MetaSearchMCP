"""Sourcegraph code search via the public streaming search API.

Sourcegraph indexes millions of public repositories and exposes a keyless
streaming search endpoint (server-sent events, SSE):

``GET https://sourcegraph.com/.api/search/stream?q=QUERY&display=N``

Each ``matches`` event carries a JSON array of content matches with the
repository, file path, commit, language, star count, and the matching lines.
No API key or authentication is required for public code search.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://sourcegraph.com/.api/search/stream"
_MAX_API_RESULTS = 50

# The streaming endpoint serves an SSE stream; without this header it may
# fall back to a non-streaming response shape.
_SSE_HEADERS: ClassVar[dict[str, str]] = {
    "Accept": "text/event-stream",
}


class SourcegraphProvider(BaseProvider):
    """Search public code across millions of repositories via Sourcegraph.

    Uses the keyless streaming search API. Each result is a code match
    inside a repository, with the file path, commit, language, star count,
    and the matched source lines.
    """

    name = "sourcegraph"
    description = (
        "Search public code across millions of repositories via Sourcegraph, "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["code", "developer", "repos"]

    @staticmethod
    def _parse_sse_events(text: str) -> list[tuple[str, Any]]:
        """Parse an SSE response body into ``(event_name, data)`` pairs.

        Events are separated by blank lines; each block contains an
        ``event:`` line and one or more ``data:`` lines whose payload is
        JSON-decoded when possible.
        """
        events: list[tuple[str, Any]] = []
        event_name = ""
        data_lines: list[str] = []

        def flush() -> None:
            nonlocal event_name, data_lines
            if not event_name or not data_lines:
                return
            payload = "\n".join(data_lines)
            try:
                data: Any = json.loads(payload)
            except json.JSONDecodeError:
                data = payload
            events.append((event_name, data))
            event_name = ""
            data_lines = []

        for line in text.splitlines():
            if not line.strip():
                flush()
                continue
            if line.startswith("event:"):
                event_name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        flush()
        return events

    @staticmethod
    def _match_url(match: dict[str, Any]) -> str:
        """Build the blob URL for a content match."""
        repository = match.get("repository", "")
        commit = match.get("commit", "")
        path = match.get("path", "")
        base = f"https://sourcegraph.com/{repository}"
        if commit:
            base += f"@{commit}"
        return f"{base}/-/blob/{path}"

    def _parse(self, text: str) -> ProviderResult:
        """Parse the SSE response body into structured code search results.

        Sourcegraph's streaming API emits matches of two relevant kinds:
        ``content`` matches (code lines matched inside a file) and ``path``
        matches (file paths whose name/path matched the query). Both carry
        the repository, path, language, and star count, so both are kept.
        """
        results: list[SearchResult] = []

        rank = 0
        for event_name, data in self._parse_sse_events(text):
            if event_name != "matches" or not isinstance(data, list):
                continue
            for item in data:
                if not isinstance(item, dict):
                    continue
                match_type = item.get("type")
                if match_type not in ("content", "path"):
                    continue
                repository = item.get("repository", "")
                path = item.get("path", "")
                if not repository or not path:
                    continue

                rank += 1
                lines = [
                    lm.get("line", "")
                    for lm in (item.get("lineMatches") or [])
                    if isinstance(lm, dict)
                ]
                line_snippet = " | ".join(lines[:5])[:MAX_SNIPPET_LENGTH]
                language = item.get("language") or ""
                stars = item.get("repoStars") or 0

                snippet_parts: list[str] = []
                if language:
                    snippet_parts.append(f"Language: {language}")
                if stars:
                    snippet_parts.append(f"Stars: {stars}")
                if lines:
                    snippet_parts.append("Lines: " + line_snippet)
                elif match_type == "path":
                    snippet_parts.append(f"Path: {path}")

                results.append(
                    SearchResult(
                        title=f"{repository} · {path}",
                        url=self._match_url(item),
                        snippet=" | ".join(p for p in snippet_parts if p),
                        source="sourcegraph.com",
                        rank=rank,
                        provider=self.name,
                        extra={
                            "match_type": match_type,
                            "repository": repository,
                            "path": path,
                            "language": language,
                            "repo_stars": stars,
                            "commit": item.get("commit", ""),
                            "matching_lines": lines[:10],
                        },
                    ),
                )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Sourcegraph for *query* and return code matches."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        headers = {**self._API_HEADERS, **_SSE_HEADERS}
        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={
                    "q": query,
                    "display": str(limit),
                },
                headers=headers,
            )
            resp.raise_for_status()
            text = resp.text

        return self._parse(text)
