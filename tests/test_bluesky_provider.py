"""Unit tests for the Bluesky social search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.providers.bluesky import BlueskyProvider

_SAMPLE_RESPONSE = {
    "posts": [
        {
            "uri": "at://did:plc:abc123/app.bsky.feed.post/3msjgvitj4k2q",
            "cid": "bafyreigzlxig6ecrwvd3lh3fhrxguqabdyh2bkktetw43svnbopkp6wpya",
            "author": {
                "did": "did:plc:abc123",
                "handle": "alice.bsky.social",
                "displayName": "Alice Example",
                "avatar": "https://cdn.bsky.app/img/avatar/plain/did:plc:abc123/avatar.jpg",
            },
            "record": {
                "$type": "app.bsky.feed.post",
                "createdAt": "2026-08-07T20:54:45.971Z",
                "langs": ["en"],
                "text": "Just learned a new Python trick!",
            },
            "bookmarkCount": 1,
            "replyCount": 2,
            "repostCount": 3,
            "likeCount": 4,
            "quoteCount": 0,
            "indexedAt": "2026-08-07T20:54:46.670Z",
        },
        {
            "uri": "at://did:plc:xyz789/app.bsky.feed.post/3msjgugsijz2j",
            "author": {
                "did": "did:plc:xyz789",
                "handle": "bob.bsky.social",
                "displayName": "",
            },
            "record": {
                "$type": "app.bsky.feed.post",
                "createdAt": "2026-08-07T20:54:10.029035+00:00",
                "text": "  A   post with   odd   spacing  ",
            },
            "bookmarkCount": 0,
            "replyCount": 0,
            "repostCount": 0,
            "likeCount": 0,
        },
        {
            "uri": "at://did:plc:nohandle/app.bsky.feed.post/3msjgv",
            "author": {"did": "did:plc:nohandle", "handle": ""},
            "record": {"$type": "app.bsky.feed.post", "createdAt": None, "text": "x"},
        },
        {
            "uri": "at://did:plc:bad/",
            "author": {"handle": "bad.bsky.social"},
            "record": "not-a-dict",
        },
    ],
}

_EMPTY_RESPONSE = {"posts": []}


def test_bluesky_parse_basic():
    p = BlueskyProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Alice Example: Just learned a new Python trick!"
    assert r.url == "https://bsky.app/profile/alice.bsky.social/post/3msjgvitj4k2q"
    assert r.snippet == "Just learned a new Python trick!"
    assert r.source == "bsky.app"
    assert r.provider == "bluesky"
    assert r.rank == 1
    assert r.published_date == "2026-08-07"
    assert r.extra["handle"] == "alice.bsky.social"
    assert r.extra["display_name"] == "Alice Example"
    assert r.extra["likes"] == 4
    assert r.extra["reposts"] == 3
    assert r.extra["replies"] == 2
    assert r.extra["bookmarks"] == 1


def test_bluesky_parse_normalizes_spacing_and_falls_back_to_handle():
    p = BlueskyProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    r = result.results[1]
    # Empty displayName falls back to the handle; whitespace is collapsed.
    assert r.title.startswith("bob.bsky.social:")
    assert "A post with odd spacing" in r.title
    assert r.snippet == "A post with odd spacing"
    assert r.extra["display_name"] == "bob.bsky.social"


def test_bluesky_parse_skips_post_without_handle_or_rkey():
    p = BlueskyProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    # Third item has no handle -> no URL; fourth has no rkey -> no URL.
    assert all(r.url for r in result.results)
    assert len(result.results) == 2


def test_bluesky_parse_empty():
    p = BlueskyProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_bluesky_parse_missing_keys():
    p = BlueskyProvider()
    result = p._parse(
        {
            "posts": [
                {
                    "uri": "at://did:plc:min/app.bsky.feed.post/abc",
                    "author": {"handle": "min.bsky.social"},
                },
            ],
        },
    )
    r = result.results[0]
    assert r.snippet == ""
    assert r.published_date is None
    assert r.extra["likes"] == 0
    assert r.extra["reposts"] == 0
    assert r.extra["replies"] == 0


def test_bluesky_post_url():
    assert (
        BlueskyProvider._post_url(
            "at://did:plc:abc/app.bsky.feed.post/rkey123", "alice.bsky.social"
        )
        == "https://bsky.app/profile/alice.bsky.social/post/rkey123"
    )
    assert BlueskyProvider._post_url("", "alice.bsky.social") == ""
    assert BlueskyProvider._post_url("at://did:plc:abc/app.bsky.feed.post", "") == ""


def test_bluesky_date_prefix():
    assert BlueskyProvider._date_prefix("2026-08-07T20:54:45.971Z") == "2026-08-07"
    assert BlueskyProvider._date_prefix(None) is None
    assert BlueskyProvider._date_prefix("not-a-date") is None


def test_bluesky_is_available():
    """Keyless provider is always available."""
    assert BlueskyProvider().is_available() is True


@pytest.mark.asyncio
async def test_bluesky_search_builds_query(respx_mock):
    """The search method hits the AppView endpoint and parses the response."""
    import respx

    respx_mock.get("https://api.bsky.app/xrpc/app.bsky.feed.searchPosts").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    from metasearchmcp.contracts import SearchParams

    p = BlueskyProvider()
    result = await p.search("python", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "bluesky"
