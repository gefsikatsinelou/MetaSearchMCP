"""Unit tests for the Gutendex (Project Gutenberg) search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.gutendex import GutendexProvider

_SAMPLE_RESPONSE = {
    "count": 231,
    "next": "https://gutendex.com/books/?page=2&search=dickens",
    "previous": None,
    "results": [
        {
            "id": 47530,
            "title": "Oliver Twist, Vol. 2 (of 3)",
            "authors": [
                {"name": "Dickens, Charles", "birth_year": 1812, "death_year": 1870},
            ],
            "summaries": ["A novel about an orphan in London."],
            "subjects": [
                "Bildungsromans",
                "Boys -- Fiction",
                "Orphans -- Fiction",
            ],
            "bookshelves": [
                "Category: British Literature",
                "Category: Classics of Literature",
            ],
            "languages": ["en"],
            "copyright": False,
            "media_type": "Text",
            "download_count": 92938,
            "formats": {
                "text/html": "https://www.gutenberg.org/ebooks/47530.html",
            },
        },
        {
            "id": 46,
            "title": "A Christmas Carol in Prose; Being a Ghost Story of Christmas",
            "authors": [
                {"name": "Dickens, Charles", "birth_year": 1812, "death_year": 1870},
            ],
            "subjects": ["Christmas stories", "Ghost stories"],
            "bookshelves": ["Category: Children's Literature"],
            "languages": ["en"],
            "copyright": False,
            "download_count": 204130,
            "formats": {
                "text/html": "https://www.gutenberg.org/ebooks/46.html",
            },
        },
    ],
}


def _provider() -> GutendexProvider:
    return GutendexProvider()


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Oliver Twist, Vol. 2 (of 3)"
    assert r.url == "https://www.gutenberg.org/ebooks/47530.html"
    assert r.provider == "gutendex"
    assert r.source == "gutendex.com"
    assert r.rank == 1
    assert r.extra["authors"] == ["Dickens, Charles"]
    assert r.extra["languages"] == ["en"]
    assert r.extra["copyright"] is False
    assert r.extra["download_count"] == 92938
    assert "By: Dickens, Charles" in r.snippet
    assert "Language: en" in r.snippet
    assert "Subjects: Bildungsromans" in r.snippet


def test_parse_falls_back_to_ebook_url_when_html_missing() -> None:
    data = {
        "results": [
            {
                "id": 123,
                "title": "No HTML format",
                "authors": [],
                "formats": {"text/plain": "https://www.gutenberg.org/ebooks/123.txt"},
            },
        ],
    }
    result = _provider()._parse(data)
    assert len(result.results) == 1
    assert result.results[0].url == "https://www.gutenberg.org/ebooks/123"


def test_parse_skips_entries_without_title_or_id() -> None:
    data = {
        "results": [
            {"title": "  ", "id": 1},
            {"id": 2, "title": ""},
            {"title": "No id"},
            "not-a-dict",
            None,
            {},
        ],
    }
    assert _provider()._parse(data).results == []


def test_parse_empty_and_malformed() -> None:
    assert _provider()._parse({}).results == []
    assert _provider()._parse({"results": "not-a-list"}).results == []
    assert _provider()._parse({"results": [None, 42]}).results == []


def test_parse_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert len(result.results) == 2


def test_string_list_dedupes_and_cleans() -> None:
    assert GutendexProvider._string_list([" en ", "en", "", "  fr"]) == ["en", "fr"]
    assert GutendexProvider._string_list(None) == []
    assert GutendexProvider._string_list("not-a-list") == []


def test_author_list_handles_malformed() -> None:
    assert GutendexProvider._author_list(None) == []
    assert GutendexProvider._author_list("not-a-list") == []
    assert GutendexProvider._author_list([{"name": "  A  "}, {"name": "A"}, None]) == [
        "A",
    ]


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_endpoint(respx_mock) -> None:
    import respx

    respx_mock.get(
        "https://gutendex.com/books/",
        params={"search": "dickens", "page": 1},
    ).mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("dickens", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "gutendex"
    assert result.results[0].url.startswith("https://www.gutenberg.org/ebooks/")
