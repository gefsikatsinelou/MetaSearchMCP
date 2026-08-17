"""Unit tests for the Google Books search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.google_books import GoogleBooksProvider

_SAMPLE_INFO: dict[str, object] = {
    "title": "Example Book Title",
    "subtitle": "A Subtitle",
    "authors": ["Jane Doe", "John Smith"],
    "publisher": "Example Press",
    "publishedDate": "2024-03-15",
    "description": "An example description of the book.",
    "pageCount": 320,
    "categories": ["Science", "Computer Science"],
    "language": "en",
    "infoLink": "https://books.google.com/books?id=abc123&dq=example",
}

_SAMPLE_ITEM: dict[str, object] = {
    "id": "abc123",
    "volumeInfo": _SAMPLE_INFO,
    "searchInfo": {"textSnippet": "An example snippet..."},
}

_SAMPLE_RESPONSE: dict[str, object] = {"totalItems": 1, "items": [_SAMPLE_ITEM]}

_EMPTY_RESPONSE: dict[str, object] = {"totalItems": 0, "items": []}


def test_google_books_parse_basic():
    p = GoogleBooksProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "Example Book Title"
    assert r.url == "https://books.google.com/books?id=abc123&dq=example"
    assert "An example snippet..." in r.snippet
    assert "By: Jane Doe, John Smith" in r.snippet
    assert "Publisher: Example Press" in r.snippet
    assert "Category: Science, Computer Science" in r.snippet
    assert r.source == "books.google.com"
    assert r.provider == "google_books"
    assert r.rank == 1
    assert r.published_date == "2024-03-15"
    assert r.extra["book_id"] == "abc123"
    assert r.extra["authors"] == ["Jane Doe", "John Smith"]
    assert r.extra["publisher"] == "Example Press"
    assert r.extra["page_count"] == "320"
    assert r.extra["language"] == "en"
    assert "example description" in r.extra["description"]


def test_google_books_parse_falls_back_to_id_url():
    p = GoogleBooksProvider()
    info = dict(_SAMPLE_INFO)
    info["infoLink"] = ""
    result = p._parse({"items": [{"id": "xyz789", "volumeInfo": info}]})
    assert result.results[0].url == "https://books.google.com/books?id=xyz789"


def test_google_books_parse_uses_description_when_no_snippet():
    p = GoogleBooksProvider()
    item = {
        "id": "abc123",
        "volumeInfo": {**_SAMPLE_INFO, "infoLink": ""},
    }
    item["volumeInfo"].pop("searchInfo", None)
    result = p._parse({"items": [item]})
    r = result.results[0]
    assert "example description" in r.snippet


def test_google_books_parse_skips_item_without_title_or_id():
    p = GoogleBooksProvider()
    result = p._parse(
        {
            "items": [
                {"id": "", "volumeInfo": {"title": "No ID"}},
                {"id": "x1", "volumeInfo": {"title": ""}},
                {"id": "x2", "volumeInfo": {}},
            ]
        }
    )
    assert result.results == []


def test_google_books_parse_empty():
    p = GoogleBooksProvider()
    assert p._parse(_EMPTY_RESPONSE).results == []


def test_google_books_parse_non_dict():
    p = GoogleBooksProvider()
    assert p._parse([{"volumeInfo": {}}]).results == []
    assert p._parse(None).results == []
    assert p._parse({"items": {"not": "a list"}}).results == []


def test_google_books_parse_handles_missing_optional_fields():
    p = GoogleBooksProvider()
    result = p._parse({"items": [{"id": "min1", "volumeInfo": {"title": "Minimal"}}]})
    r = result.results[0]
    assert r.snippet == ""
    assert r.published_date is None
    assert r.extra["authors"] == []
    assert r.extra["publisher"] == ""
    assert r.extra["categories"] == []


def test_google_books_parse_skips_non_dict_items():
    p = GoogleBooksProvider()
    result = p._parse({"items": ["junk", 42, _SAMPLE_ITEM]})
    assert len(result.results) == 1


def test_google_books_clean_text():
    assert GoogleBooksProvider._clean_text("  a\n  b  ") == "a b"
    assert GoogleBooksProvider._clean_text(None) == ""
    assert GoogleBooksProvider._clean_text("") == ""


def test_google_books_is_available():
    """Keyless provider is always available."""
    assert GoogleBooksProvider().is_available() is True


@pytest.mark.asyncio
async def test_google_books_search_hits_api_and_parses(respx_mock):
    """The search method hits the volumes endpoint and parses the response."""
    import respx

    respx_mock.get("https://www.googleapis.com/books/v1/volumes").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = GoogleBooksProvider()
    result = await p.search("python programming", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "google_books"
    assert result.results[0].title == "Example Book Title"


@pytest.mark.asyncio
async def test_google_books_search_empty_response(respx_mock):
    """An empty items list yields no results."""
    import respx

    respx_mock.get("https://www.googleapis.com/books/v1/volumes").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = GoogleBooksProvider()
    result = await p.search("zzz", SearchParams(num_results=5))

    assert result.results == []


@pytest.mark.asyncio
async def test_google_books_search_truncates_to_limit(respx_mock):
    """The search method truncates results to the requested limit."""
    import respx

    many = {
        "items": [
            {
                "id": f"book{i}",
                "volumeInfo": {"title": f"Book {i}", "infoLink": ""},
            }
            for i in range(1, 6)
        ]
    }
    respx_mock.get("https://www.googleapis.com/books/v1/volumes").mock(
        return_value=respx.MockResponse(200, json=many),
    )

    p = GoogleBooksProvider()
    result = await p.search("books", SearchParams(num_results=2))

    assert len(result.results) == 2
    assert result.results[0].title == "Book 1"


@pytest.mark.asyncio
async def test_google_books_search_passes_query_param(respx_mock):
    """The search method forwards the query and result limit as parameters."""
    import respx

    route = respx_mock.get("https://www.googleapis.com/books/v1/volumes").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = GoogleBooksProvider()
    await p.search("open science", SearchParams(num_results=3))

    request = route.calls.last.request
    assert request.url.params["q"] == "open science"
    assert request.url.params["maxResults"] == "3"
    assert request.url.params["country"] == "US"
