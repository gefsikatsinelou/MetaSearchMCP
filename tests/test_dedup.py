"""Tests for URL canonicalization and hit merging."""

from __future__ import annotations

from metasearchmcp.contracts import SearchHit
from metasearchmcp.merge import canonicalize_url, collapse_duplicate_hits


def _r(url: str, provider: str = "p") -> SearchHit:
    return SearchHit(title="T", url=url, provider=provider)


# --- URL normalization ---


def test_normalize_strips_trailing_slash():
    assert canonicalize_url("https://example.com/foo/") == canonicalize_url(
        "https://example.com/foo"
    )


def test_normalize_case_insensitive():
    assert canonicalize_url("https://Example.COM/Foo") == canonicalize_url(
        "https://example.com/foo"
    )


def test_normalize_drops_fragment():
    assert canonicalize_url("https://example.com/foo#bar") == canonicalize_url(
        "https://example.com/foo"
    )


def test_normalize_preserves_query():
    a = canonicalize_url("https://example.com/foo?q=1")
    b = canonicalize_url("https://example.com/foo?q=2")
    assert a != b


def test_normalize_drops_tracking_query_params():
    assert canonicalize_url(
        "https://example.com/foo?q=python&utm_source=newsletter&fbclid=abc123"
    ) == canonicalize_url("https://example.com/foo?q=python")


def test_normalize_sorts_query_params_for_stable_deduplication():
    assert canonicalize_url("https://example.com/foo?b=2&a=1") == canonicalize_url(
        "https://example.com/foo?a=1&b=2"
    )


def test_normalize_drops_default_ports():
    assert canonicalize_url("https://example.com:443/foo") == canonicalize_url(
        "https://example.com/foo"
    )
    assert canonicalize_url("http://example.com:80/foo") == canonicalize_url(
        "http://example.com/foo"
    )


def test_normalize_preserves_non_default_ports():
    assert canonicalize_url("https://example.com:8443/foo") != canonicalize_url(
        "https://example.com/foo"
    )


# --- Deduplication ---


def test_dedup_removes_exact_duplicates():
    results = [_r("https://a.com"), _r("https://a.com"), _r("https://b.com")]
    out = collapse_duplicate_hits(results)
    assert len(out) == 2
    assert out[0].url == "https://a.com"
    assert out[1].url == "https://b.com"


def test_dedup_first_occurrence_wins():
    r1 = SearchHit(title="First", url="https://a.com", provider="p1")
    r2 = SearchHit(title="Second", url="https://a.com", provider="p2")
    out = collapse_duplicate_hits([r1, r2])
    assert len(out) == 1
    assert out[0].provider == "p1"


def test_dedup_trailing_slash_same():
    out = collapse_duplicate_hits([_r("https://a.com/foo/"), _r("https://a.com/foo")])
    assert len(out) == 1


def test_dedup_tracking_links_same():
    out = collapse_duplicate_hits(
        [
            _r("https://a.com/foo?q=python&utm_medium=email"),
            _r("https://a.com/foo?q=python"),
        ]
    )
    assert len(out) == 1


def test_dedup_empty_list():
    assert collapse_duplicate_hits([]) == []


def test_dedup_no_duplicates_unchanged():
    results = [_r("https://a.com"), _r("https://b.com"), _r("https://c.com")]
    out = collapse_duplicate_hits(results)
    assert len(out) == 3


def test_dedup_skips_empty_urls():
    results = [_r(""), _r(""), _r("https://a.com")]
    out = collapse_duplicate_hits(results)
    # Empty URL entries are skipped (key is empty string which is falsy)
    assert len(out) == 1
    assert out[0].url == "https://a.com"
