"""Search query suggestions via the public, keyless DuckDuckGo autocomplete API.

DuckDuckGo exposes an unauthenticated autocomplete endpoint:

``GET https://duckduckgo.com/ac/?q=QUERY&type=list``

It returns a two-element JSON array: ``["query", ["suggestion", ...]]``.
No API key or authentication is required; parsing uses only the standard
library plus the shared httpx client pattern from the base provider.
"""

from __future__ import annotations

from typing import Any

import httpx

from metasearchmcp.providers.base import API_USER_AGENT

_AC_URL = "https://duckduckgo.com/ac/"
# DuckDuckGo autocomplete returns at most 20 phrases per request.
_MAX_API_SUGGESTIONS = 20

_HEADERS = {"User-Agent": API_USER_AGENT}


async def fetch_suggestions(query: str, limit: int = 8) -> list[str]:
    """Fetch autocomplete suggestions for *query* from DuckDuckGo.

    Args:
        query: The search prefix to complete.
        limit: Maximum number of suggestions to return (capped at 20).

    Returns:
        A list of suggestion strings. Returns an empty list when the
        upstream request fails or returns no suggestions.
    """
    capped = max(1, min(int(limit), _MAX_API_SUGGESTIONS))
    params = {"q": query, "type": "list"}
    try:
        async with httpx.AsyncClient(
            timeout=5.0,
            follow_redirects=True,
            headers=_HEADERS,
        ) as client:
            resp = await client.get(_AC_URL, params=params)
            resp.raise_for_status()
            data: Any = resp.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return []

    if not isinstance(data, list) or len(data) < 2:
        return []
    suggestions = data[1]
    if not isinstance(suggestions, list):
        return []

    cleaned: list[str] = []
    for item in suggestions:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= capped:
            break
    return cleaned
