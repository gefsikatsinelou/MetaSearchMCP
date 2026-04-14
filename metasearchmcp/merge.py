from __future__ import annotations

from urllib.parse import urlparse, urlunparse

from metasearchmcp.contracts import SearchHit


def canonicalize_url(url: str) -> str:
    """Normalize URLs so multi-engine duplicates collapse cleanly."""
    try:
        parsed = urlparse(url.strip().lower())
        path = parsed.path.rstrip("/") or "/"
        normalized = urlunparse(
            ("", parsed.netloc, path, parsed.params, parsed.query, "")
        )
        return normalized.lstrip("/")
    except Exception:
        return url.strip().lower()


def collapse_duplicate_hits(results: list[SearchHit]) -> list[SearchHit]:
    """Keep the first hit for each canonical URL."""
    seen: set[str] = set()
    unique: list[SearchHit] = []
    for result in results:
        key = canonicalize_url(result.url)
        if key and key not in seen:
            seen.add(key)
            unique.append(result)
    return unique
