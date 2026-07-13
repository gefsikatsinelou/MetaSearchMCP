"""Tests for the You.com provider."""

from __future__ import annotations

from metasearchmcp.config import get_settings


def _youcom_response() -> dict:
    return {
        "results": {
            "web": [
                {
                    "url": "https://example.com/guide",
                    "title": "Example Guide",
                    "description": "A practical guide.",
                    "snippets": ["A practical guide snippet."],
                    "page_age": "2026-07-01T12:30:00",
                    "thumbnail_url": "https://example.com/thumb.png",
                    "favicon_url": "https://example.com/favicon.ico",
                }
            ],
            "news": [
                {
                    "url": "https://news.example.com/story",
                    "title": "Example News",
                    "description": "Latest story.",
                    "page_age": "2026-07-02T09:00:00",
                }
            ],
        }
    }


def test_youcom_parse_merges_web_and_news_results():
    from metasearchmcp.providers.youcom import YouComProvider

    provider = YouComProvider()
    result = provider._parse(_youcom_response())

    assert len(result.results) == 2
    first = result.results[0]
    assert first.title == "Example Guide"
    assert first.url == "https://example.com/guide"
    assert first.provider == "youcom"
    assert first.published_date == "2026-07-01"
    assert first.extra["thumbnail_url"] == "https://example.com/thumb.png"

    second = result.results[1]
    assert second.title == "Example News"
    assert second.rank == 2
    assert second.published_date == "2026-07-02"


def test_youcom_parse_falls_back_to_first_snippet_when_description_missing():
    from metasearchmcp.providers.youcom import YouComProvider

    provider = YouComProvider()
    result = provider._parse(
        {
            "results": {
                "web": [
                    {
                        "url": "https://example.com",
                        "title": "Example",
                        "description": "",
                        "snippets": ["Fallback snippet"],
                    }
                ]
            }
        },
    )

    assert result.results[0].snippet == "Fallback snippet"


def test_youcom_availability_requires_api_key(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("YDC_API_KEY", "")

    from metasearchmcp.providers.youcom import YouComProvider

    provider = YouComProvider()
    assert provider.is_available() is False

    get_settings.cache_clear()
    monkeypatch.setenv("YDC_API_KEY", "test-key")
    provider = YouComProvider()
    assert provider.is_available() is True
    get_settings.cache_clear()
