"""Unit tests for the Mastodon social search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.providers.mastodon import MastodonProvider

_SAMPLE_RESPONSE = {
    "accounts": [],
    "statuses": [
        {
            "id": "103270115826975975",
            "created_at": "2019-12-08T04:05:50.000Z",
            "content": (
                '<p>Hello <a href="https://example.com">fediverse</a>!'
                " This is a test post about python.</p>"
            ),
            "url": "https://mastodon.social/@alice/103270115826975975",
            "reblogs_count": 3,
            "favourites_count": 12,
            "replies_count": 1,
            "account": {
                "acct": "alice",
                "display_name": "Alice",
                "url": "https://mastodon.social/@alice",
            },
        },
        {
            "id": "103270115826975976",
            "created_at": "2020-01-01T00:00:00.000Z",
            "content": "<p>Another status without links</p>",
            "url": "https://mastodon.social/@bob/103270115826975976",
            "reblogs_count": 0,
            "favourites_count": 0,
            "replies_count": 0,
            "account": {
                "acct": "bob",
                "display_name": "",
                "url": "https://mastodon.social/@bob",
            },
        },
        {
            "id": "103270115826975977",
            "created_at": "not-a-date",
            "content": "",
            "url": "",
            "reblogs_count": 0,
            "favourites_count": 0,
            "replies_count": 0,
            "account": {"acct": "carol", "display_name": "Carol"},
        },
    ],
    "hashtags": [],
}

_EMPTY_RESPONSE = {"accounts": [], "statuses": [], "hashtags": []}


def test_mastodon_parse_basic():
    p = MastodonProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert "fediverse" in r.title
    assert "fediverse" in r.snippet
    assert "test post about python" in r.snippet
    assert r.url == "https://mastodon.social/@alice/103270115826975975"
    assert r.source == "mastodon.social"
    assert r.provider == "mastodon"
    assert r.rank == 1
    assert r.published_date == "2019-12-08"
    assert r.extra["account"] == "alice"
    assert r.extra["reblogs"] == 3
    assert r.extra["favourites"] == 12
    assert r.extra["replies"] == 1


def test_mastodon_parse_second_status():
    """Empty display name falls back to the account handle in extra."""
    p = MastodonProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    r = result.results[1]

    assert r.published_date == "2020-01-01"
    assert r.extra["account"] == "bob"
    assert r.extra["reblogs"] == 0


def test_mastodon_parse_skips_status_without_url():
    p = MastodonProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    assert all(r.url for r in result.results)


def test_mastodon_parse_empty():
    p = MastodonProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_mastodon_plain_text_strips_html():
    assert (
        MastodonProvider._plain_text(
            '<p>Hello <a href="https://x.com">world</a>!</p>',
        )
        == "Hello world !"
    )
    assert MastodonProvider._plain_text("") == ""
    assert MastodonProvider._plain_text("<p>  spaced   out  </p>") == "spaced out"


def test_mastodon_date_prefix():
    assert MastodonProvider._date_prefix("2019-12-08T04:05:50.000Z") == "2019-12-08"
    assert MastodonProvider._date_prefix("2020-01-01T00:00:00+00:00") == "2020-01-01"
    assert MastodonProvider._date_prefix("not-a-date") is None
    assert MastodonProvider._date_prefix("") is None
    assert MastodonProvider._date_prefix(None) is None


def test_mastodon_is_available():
    """Keyless provider is always available."""
    assert MastodonProvider().is_available() is True


@pytest.mark.asyncio
async def test_mastodon_search_builds_query(respx_mock):
    """The search method hits the API v2 endpoint and parses the response."""
    import respx

    respx_mock.get("https://mastodon.social/api/v2/search").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    from metasearchmcp.contracts import SearchParams

    p = MastodonProvider()
    result = await p.search("python", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "mastodon"
