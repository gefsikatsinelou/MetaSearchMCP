"""Unit tests for the Open Library search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.openlibrary import OpenLibraryProvider

_SAMPLE_RESPONSE = {
    "numFound": 17423,
    "docs": [
        {
            "key": "/works/OL34221W",
            "title": "A Tale of Two Cities",
            "author_name": ["Charles Dickens"],
            "first_publish_year": 1859,
            "latest_publish_year": 2023,
            "edition_count": 280,
            "language": ["eng", "fre"],
            "subject": ["Fiction", "England", "London (England)"],
            "cover_i": 13301713,
            "ia": ["taleoftwocities0000char_e9x4"],
        },
        {
            "key": "/works/OL15230687W",
            "title": "Oliver Twist",
            "author_name": ["Charles Dickens"],
            "first_publish_year": 1838,
            "edition_count": 400,
            "language": ["eng"],
            "subject": ["Orphans", "Fiction"],
        },
        {
            "key": "/works/OL44915W",
            "title": "A Christmas Carol",
            "author_name": ["Charles Dickens", "Roberto Innocenti"],
            "first_publish_year": 1843,
            "edition_count": 390,
            "language": ["eng", "spa", "deu", "ita"],
            "subject": ["Christmas stories"],
        },
        "not-a-dict",
        None,
        {"title": "No key"},
        {"key": "/works/OL1W", "title": "  "},
    ],
}


def _provider() -> OpenLibraryProvider:
    return OpenLibraryProvider()


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 3
    r = result.results[0]
    assert r.title == "A Tale of Two Cities"
    assert r.url == "https://openlibrary.org/works/OL34221W"
    assert r.provider == "openlibrary"
    assert r.source == "openlibrary.org"
    assert r.rank == 1
    assert r.published_date == "1859"
    assert r.extra["authors"] == ["Charles Dickens"]
    assert r.extra["edition_count"] == 280
    assert r.extra["cover_url"] == "https://covers.openlibrary.org/b/id/13301713-M.jpg"
    assert r.extra["archive_id"] == "taleoftwocities0000char_e9x4"
    assert (
        r.extra["readable_url"]
        == "https://archive.org/details/taleoftwocities0000char_e9x4"
    )
    assert "By: Charles Dickens" in r.snippet
    assert "First published: 1859" in r.snippet
    assert "Subjects: Fiction, England" in r.snippet


def test_parse_handles_missing_optional_fields() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    r = result.results[1]
    assert r.extra["cover_url"] == ""
    assert r.extra["archive_id"] == ""
    assert r.extra["readable_url"] == ""
    assert r.published_date == "1838"


def test_parse_skips_malformed_entries() -> None:
    assert _provider()._parse(_SAMPLE_RESPONSE).results[2].title == "A Christmas Carol"
    assert _provider()._parse({}).results == []
    assert _provider()._parse({"docs": "not-a-list"}).results == []
    assert _provider()._parse({"docs": [None, 42, "x"]}).results == []


def test_parse_uses_publish_year_fallback() -> None:
    data = {
        "docs": [
            {
                "key": "/works/OL9W",
                "title": "Undated work",
                "publish_year": [1965],
            },
        ],
    }
    r = _provider()._parse(data).results[0]
    assert r.published_date == "1965"
    assert r.extra["first_publish_year"] == 1965


def test_string_list_cleans_and_dedupes() -> None:
    assert OpenLibraryProvider._string_list([" A ", "A", "", " b"]) == ["A", "b"]
    assert OpenLibraryProvider._string_list(None) == []
    assert OpenLibraryProvider._string_list("not-a-list") == []


def test_clean_text_collapses_whitespace() -> None:
    assert OpenLibraryProvider._clean_text("  a   b\nc ") == "a b c"
    assert OpenLibraryProvider._clean_text(None) == ""
    assert OpenLibraryProvider._clean_text(0) == "0"


def test_first_scalar_normalizes_scalars_and_lists() -> None:
    assert OpenLibraryProvider._first_scalar(1859) == 1859
    assert OpenLibraryProvider._first_scalar([1965]) == 1965
    assert OpenLibraryProvider._first_scalar("taleoftwocities") == "taleoftwocities"
    assert OpenLibraryProvider._first_scalar(["taleoftwocities"]) == "taleoftwocities"
    assert OpenLibraryProvider._first_scalar(["", "  ", "b"]) == "b"
    assert OpenLibraryProvider._first_scalar([]) is None
    assert OpenLibraryProvider._first_scalar(None) is None
    assert OpenLibraryProvider._first_scalar(0) is None
    assert OpenLibraryProvider._first_scalar("") is None
    assert OpenLibraryProvider._first_scalar(3.14) is None
    assert OpenLibraryProvider._first_scalar([0]) is None


def test_cover_url() -> None:
    assert OpenLibraryProvider._cover_url(42) == (
        "https://covers.openlibrary.org/b/id/42-M.jpg"
    )
    assert OpenLibraryProvider._cover_url(0) == ""
    assert OpenLibraryProvider._cover_url(None) == ""
    assert OpenLibraryProvider._cover_url("") == ""


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_endpoint(respx_mock) -> None:
    import respx

    respx_mock.get("https://openlibrary.org/search.json").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("dickens", SearchParams(num_results=5))

    assert len(result.results) == 3
    assert result.results[0].provider == "openlibrary"
    assert result.results[0].url.startswith("https://openlibrary.org/")
    assert (
        result.results[0]
        .extra["cover_url"]
        .startswith(
            "https://covers.openlibrary.org/",
        )
    )
