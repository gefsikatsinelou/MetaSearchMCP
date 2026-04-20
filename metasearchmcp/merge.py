from __future__ import annotations

from urllib.parse import urlparse, urlunparse

from metasearchmcp.contracts import SearchHit

_DEFAULT_PORTS = {"http": "80", "https": "443"}


def _drop_default_port(scheme: str, netloc: str) -> str:
    host, separator, port = netloc.rpartition(":")
    if not separator or _DEFAULT_PORTS.get(scheme) != port:
        return netloc
    return host


def canonicalize_url(url: str) -> str:
    """Normalize URLs so multi-engine duplicates collapse cleanly."""
    try:
        parsed = urlparse(url.strip().lower())
        netloc = _drop_default_port(parsed.scheme, parsed.netloc)
        path = parsed.path.rstrip("/") or "/"
        normalized = urlunparse(
            ("", netloc, path, parsed.params, parsed.query, "")
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
