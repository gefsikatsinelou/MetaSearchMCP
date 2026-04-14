"""Parse/adapter tests for the new providers added in the second batch."""
from __future__ import annotations


# ---------------------------------------------------------------------------
# HackerNews
# ---------------------------------------------------------------------------

def _hn_response() -> dict:
    return {
        "hits": [
            {
                "objectID": "12345",
                "title": "Ask HN: Best async Python libraries?",
                "url": "https://example.com/article",
                "author": "user123",
                "points": 250,
                "num_comments": 87,
                "created_at": "2024-03-10T12:00:00.000Z",
            },
            {
                "objectID": "99999",
                "title": "Show HN: My new project",
                "url": "",   # self post, no external URL
                "author": "maker",
                "points": 50,
                "num_comments": 10,
                "created_at": "2024-03-11T08:00:00.000Z",
            },
        ]
    }


def test_hackernews_parse():
    from metasearchmcp.providers.hackernews import HackerNewsProvider
    p = HackerNewsProvider()
    result = p._parse(_hn_response())

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Ask HN: Best async Python libraries?"
    assert r.url == "https://example.com/article"
    assert r.provider == "hackernews"
    assert r.extra["points"] == 250
    assert r.published_date == "2024-03-10"


def test_hackernews_self_post_uses_hn_url():
    from metasearchmcp.providers.hackernews import HackerNewsProvider
    p = HackerNewsProvider()
    result = p._parse(_hn_response())
    # second result has no external URL -> should use HN permalink
    r = result.results[1]
    assert "news.ycombinator.com" in r.url


# ---------------------------------------------------------------------------
# npm
# ---------------------------------------------------------------------------

def _npm_response() -> dict:
    return {
        "objects": [
            {
                "package": {
                    "name": "lodash",
                    "version": "4.17.21",
                    "description": "Lodash modular utilities",
                    "keywords": ["modules", "stdlib", "util"],
                    "date": "2021-02-20T15:42:16.891Z",
                    "links": {"npm": "https://www.npmjs.com/package/lodash"},
                },
                "score": {"final": 0.95},
            }
        ]
    }


def test_npm_parse():
    from metasearchmcp.providers.npm import NpmProvider
    p = NpmProvider()
    result = p._parse(_npm_response())

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "lodash"
    assert r.url == "https://www.npmjs.com/package/lodash"
    assert r.provider == "npm"
    assert "4.17.21" in r.snippet
    assert r.extra["version"] == "4.17.21"
    assert r.published_date == "2021-02-20"


# ---------------------------------------------------------------------------
# crates.io
# ---------------------------------------------------------------------------

def _crates_response() -> dict:
    return {
        "crates": [
            {
                "name": "serde",
                "newest_version": "1.0.197",
                "description": "A generic serialization/deserialization framework",
                "downloads": 500_000_000,
                "recent_downloads": 20_000_000,
                "updated_at": "2024-02-15T00:00:00.000000+00:00",
            }
        ]
    }


def test_crates_parse():
    from metasearchmcp.providers.crates import CratesIoProvider
    p = CratesIoProvider()
    result = p._parse(_crates_response())

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "serde"
    assert r.url == "https://crates.io/crates/serde"
    assert r.provider == "crates"
    assert r.extra["downloads"] == 500_000_000
    assert r.published_date == "2024-02-15"


# ---------------------------------------------------------------------------
# Reddit
# ---------------------------------------------------------------------------

def _reddit_response() -> dict:
    return {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "What is the best way to learn Rust?",
                        "url": "https://www.reddit.com/r/rust/comments/abc/",
                        "permalink": "/r/rust/comments/abc/",
                        "subreddit_name_prefixed": "r/rust",
                        "score": 1200,
                        "num_comments": 340,
                        "is_self": True,
                        "selftext": "I am looking for resources...",
                        "created_utc": 1709827200.0,
                    }
                }
            ]
        }
    }


def test_reddit_parse():
    from metasearchmcp.providers.reddit import RedditProvider
    p = RedditProvider()
    result = p._parse(_reddit_response())

    assert len(result.results) == 1
    r = result.results[0]
    assert r.provider == "reddit"
    assert r.extra["score"] == 1200
    assert r.extra["subreddit"] == "r/rust"
    assert r.published_date is not None


# ---------------------------------------------------------------------------
# Stack Overflow
# ---------------------------------------------------------------------------

def _so_response() -> dict:
    return {
        "items": [
            {
                "title": "How do I use async/await in Python?",
                "link": "https://stackoverflow.com/questions/1234/async-await",
                "score": 450,
                "answer_count": 12,
                "is_answered": True,
                "tags": ["python", "async", "asyncio"],
            }
        ]
    }


def test_stackoverflow_parse():
    from metasearchmcp.providers.stackoverflow import StackOverflowProvider
    p = StackOverflowProvider()
    result = p._parse(_so_response())

    assert len(result.results) == 1
    r = result.results[0]
    assert r.url == "https://stackoverflow.com/questions/1234/async-await"
    assert r.provider == "stackoverflow"
    assert r.extra["is_answered"] is True
    assert "asyncio" in r.extra["tags"]


# ---------------------------------------------------------------------------
# Wikidata
# ---------------------------------------------------------------------------

def _wikidata_response() -> dict:
    return {
        "search": [
            {
                "id": "Q9903",
                "label": "Python",
                "description": "high-level programming language",
                "url": "//www.wikidata.org/wiki/Q9903",
                "aliases": ["Python language"],
            }
        ]
    }


def test_wikidata_parse():
    from metasearchmcp.providers.wikidata import WikidataProvider
    p = WikidataProvider()
    result = p._parse(_wikidata_response(), "en")

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Python"
    assert r.url.startswith("https://")
    assert "programming language" in r.snippet
    assert r.extra["entity_id"] == "Q9903"


# ---------------------------------------------------------------------------
# Internet Archive
# ---------------------------------------------------------------------------

def _ia_response() -> dict:
    return {
        "response": {
            "docs": [
                {
                    "identifier": "free-culture-lessig",
                    "title": "Free Culture",
                    "description": "Lawrence Lessig on free culture and copyright",
                    "mediatype": "texts",
                    "date": "2004-01-01",
                    "creator": "Lawrence Lessig",
                }
            ]
        }
    }


def test_internet_archive_parse():
    from metasearchmcp.providers.internet_archive import InternetArchiveProvider
    p = InternetArchiveProvider()
    result = p._parse(_ia_response())

    assert len(result.results) == 1
    r = result.results[0]
    assert r.url == "https://archive.org/details/free-culture-lessig"
    assert r.provider == "internet_archive"
    assert r.extra["mediatype"] == "texts"


# ---------------------------------------------------------------------------
# Semantic Scholar
# ---------------------------------------------------------------------------

def _s2_response() -> dict:
    return {
        "data": [
            {
                "paperId": "abc123",
                "title": "BERT: Pre-training of Deep Bidirectional Transformers",
                "abstract": "We introduce BERT, a language representation model.",
                "year": 2019,
                "venue": "NAACL",
                "citationCount": 50000,
                "authors": [
                    {"name": "Jacob Devlin"},
                    {"name": "Ming-Wei Chang"},
                    {"name": "Kenton Lee"},
                    {"name": "Kristina Toutanova"},
                ],
                "externalIds": {"DOI": "10.18653/v1/N19-1423"},
            }
        ]
    }


def test_semanticscholar_parse():
    from metasearchmcp.providers.semanticscholar import SemanticScholarProvider
    p = SemanticScholarProvider()
    result = p._parse(_s2_response())

    assert len(result.results) == 1
    r = result.results[0]
    assert "BERT" in r.title
    assert r.url == "https://doi.org/10.18653/v1/N19-1423"
    assert r.provider == "semanticscholar"
    assert r.extra["citation_count"] == 50000
    assert "et al." in r.extra["authors"] or len(r.extra["authors"]) == 4


# ---------------------------------------------------------------------------
# CrossRef
# ---------------------------------------------------------------------------

def _crossref_response() -> dict:
    return {
        "message": {
            "items": [
                {
                    "DOI": "10.1145/3292500.3330701",
                    "title": ["KDD 2019: Knowledge Discovery and Data Mining"],
                    "URL": "https://doi.org/10.1145/3292500.3330701",
                    "abstract": "<jats:p>Data mining proceedings.</jats:p>",
                    "author": [
                        {"given": "Alice", "family": "Smith"},
                        {"given": "Bob", "family": "Jones"},
                    ],
                    "container-title": ["Proceedings of KDD"],
                    "is-referenced-by-count": 300,
                    "type": "proceedings-article",
                    "published": {"date-parts": [[2019, 8, 4]]},
                }
            ]
        }
    }


def test_crossref_parse():
    from metasearchmcp.providers.crossref import CrossrefProvider
    p = CrossrefProvider()
    result = p._parse(_crossref_response())

    assert len(result.results) == 1
    r = result.results[0]
    assert r.url == "https://doi.org/10.1145/3292500.3330701"
    assert r.provider == "crossref"
    assert r.published_date == "2019-08-04"
    # JATS tags should be stripped from abstract
    assert "<jats:" not in r.snippet
    assert r.extra["citation_count"] == 300


# ---------------------------------------------------------------------------
# PubMed
# ---------------------------------------------------------------------------

def _pubmed_summary() -> dict:
    return {
        "result": {
            "12345": {
                "title": "CRISPR-Cas9 genome editing",
                "pubdate": "2023 Mar",
                "source": "Nature Methods",
                "authors": [
                    {"name": "Zhang F"},
                    {"name": "Smith J"},
                ],
            }
        }
    }


def test_pubmed_parse():
    from metasearchmcp.providers.pubmed import PubMedProvider
    p = PubMedProvider()
    result = p._parse(_pubmed_summary(), ["12345"])

    assert len(result.results) == 1
    r = result.results[0]
    assert r.url == "https://pubmed.ncbi.nlm.nih.gov/12345/"
    assert r.provider == "pubmed"
    assert r.extra["pmid"] == "12345"
    assert "Nature Methods" in r.snippet


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------

def test_registry_imports_all_providers():
    """Smoke test: all provider classes can be instantiated without error."""
    from metasearchmcp.providers.registry import _ALL_PROVIDER_CLASSES
    assert len(_ALL_PROVIDER_CLASSES) >= 26
    for cls in _ALL_PROVIDER_CLASSES:
        instance = cls()
        assert instance.name != ""
        assert isinstance(instance.tags, list)
