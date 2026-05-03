from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from metasearchmcp.contracts import SearchHit

_DEFAULT_PORTS = {"http": "80", "https": "443"}
_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "mkt_tok",
    "ref_src",
}


def _drop_default_port(scheme: str, netloc: str) -> str:
    host, separator, port = netloc.rpartition(":")
    if not separator or _DEFAULT_PORTS.get(scheme) != port:
        return netloc
    return host


def _normalize_query(query: str) -> str:
    if not query:
        return ""

    filtered = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        normalized_key = key.lower()
        if normalized_key.startswith("utm_") or normalized_key in _TRACKING_QUERY_KEYS:
            continue
        filtered.append((normalized_key, value))

    if not filtered:
        return ""

    filtered.sort()
    return urlencode(filtered, doseq=True)


def canonicalize_url(url: str) -> str:
    """Normalize URLs so multi-engine duplicates collapse cleanly."""
    try:
        parsed = urlparse(url.strip().lower())
        netloc = _drop_default_port(parsed.scheme, parsed.netloc)
        path = parsed.path.rstrip("/") or "/"
        query = _normalize_query(parsed.query)
        normalized = urlunparse(("", netloc, path, parsed.params, query, ""))
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
