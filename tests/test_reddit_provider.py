"""Unit tests for the Reddit JSON search provider.

Covers parsing of the Reddit search JSON API response (listing structure,
optional ``media_embed``/``preview`` blocks, missing ``selftext``), the
``over_18`` flag propagation, and availability.
"""

from __future__ import annotations

import pytest
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.reddit import RedditProvider


def _post(
    *,
    title: str,
    permalink: str,
    selftext: str = "",
    subreddit: str = "python",
    score: int = 100,
    num_comments: int = 10,
    over_18: bool = False,
    created_utc: float = 1_700_000_000.0,
    is_self: bool = True,
    url: str = "",
    **extra: object,
) -> dict:
    """Build a Reddit ``t3`` child dict with the fields the parser reads."""
    data: dict = {
        "kind": "t3",
        "data": {
            "title": title,
            "permalink": permalink,
            "selftext": selftext,
            "subreddit": subreddit,
            "score": score,
            "num_comments": num_comments,
            "over_18": over_18,
            "created_utc": created_utc,
            "is_self": is_self,
            "url": url,
        },
    }
    data["data"].update(extra)
    return data


def _payload(*posts: dict) -> dict:
    """Wrap child posts in a Reddit search listing response."""
    return {
        "kind": "Listing",
        "data": {
            "children": list(posts),
            "dist": len(posts),
        },
    }


def _provider() -> RedditProvider:
    return RedditProvider()


def test_parse_basic() -> None:
    p = _provider()
    result = p._parse(
        _payload(
            _post(
                title="Async Python: asyncio for beginners",
                permalink="/r/python/comments/abc/async_python/",
                selftext="A tutorial on asyncio.",
                score=250,
                num_comments=87,
            ),
            _post(
                title="FastAPI vs Flask in 2024",
                permalink="/r/Python/comments/def/fastapi_vs_flask/",
                selftext="",
                score=50,
                num_comments=3,
            ),
        ),
    )

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Async Python: asyncio for beginners"
    assert r.url == "https://www.reddit.com/r/python/comments/abc/async_python/"
    assert r.provider == "reddit"
    assert r.rank == 1
    assert r.source == "reddit.com"
    assert "asyncio" in r.snippet
    assert r.extra["score"] == 250
    assert r.extra["subreddit"] == ""

    assert result.results[1].rank == 2
    # Empty selftext must not crash and yields an empty snippet.
    assert result.results[1].snippet == ""


def test_parse_link_post_uses_external_url() -> None:
    """Link posts surface their external URL; permalink stays in extra."""
    p = _provider()
    result = p._parse(
        _payload(
            _post(
                title="Link post",
                permalink="/r/python/comments/1/link/",
                is_self=False,
                url="https://example.com/article",
            ),
        ),
    )
    r = result.results[0]
    assert r.url == "https://example.com/article"
    assert r.extra["permalink"] == "https://www.reddit.com/r/python/comments/1/link/"


def test_parse_uses_subreddit_name_prefixed() -> None:
    p = _provider()
    result = p._parse(
        _payload(
            _post(
                title="With prefix",
                permalink="/r/python/comments/1/with/",
                subreddit_name_prefixed="r/python",
            ),
        ),
    )
    r = result.results[0]
    assert r.extra["subreddit"] == "r/python"
    assert "r/python" in r.snippet


def test_parse_skips_non_t3_kinds() -> None:
    p = _provider()
    result = p._parse(
        _payload(
            _post(
                title="Keep me",
                permalink="/r/x/comments/1/keep/",
                subreddit_name_prefixed="r/x",
            ),
            {"kind": "t5", "data": {"title": "Subreddit meta", "permalink": "/r/x/"}},
        ),
    )
    assert len(result.results) == 1
    assert result.results[0].title == "Keep me"


def test_parse_flags_over_18() -> None:
    p = _provider()
    result = p._parse(
        _payload(
            _post(
                title="Safe",
                permalink="/r/x/comments/1/safe/",
                subreddit_name_prefixed="r/x",
            ),
            _post(
                title="NSFW",
                permalink="/r/x/comments/2/nsfw/",
                over_18=True,
                subreddit_name_prefixed="r/x",
            ),
        ),
    )
    nsfw = next(r for r in result.results if r.title == "NSFW")
    assert nsfw.extra.get("over_18") is True
    safe = next(r for r in result.results if r.title == "Safe")
    assert safe.extra.get("over_18") is False


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse({}).results == []
    assert p._parse({"kind": "Listing", "data": {"children": []}}).results == []
    assert p._parse({"kind": "Listing", "data": {}}).results == []


def test_is_available() -> None:
    """Reddit requires OAuth2 credentials, so availability is key-gated."""
    assert _provider().is_available() is False


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    """Exercise the OAuth2 token + search flow against mocked endpoints."""
    import respx

    respx_mock.post("https://www.reddit.com/api/v1/access_token").mock(
        return_value=respx.MockResponse(200, json={"access_token": "tok123"}),
    )
    respx_mock.get("https://oauth.reddit.com/search.json").mock(
        return_value=respx.MockResponse(
            200,
            json=_payload(
                _post(
                    title="Async Python: asyncio for beginners",
                    permalink="/r/python/comments/abc/async_python/",
                    subreddit_name_prefixed="r/python",
                ),
            ),
        ),
    )

    import metasearchmcp.config as cfg

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("REDDIT_CLIENT_ID", "cid")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "csecret")
    cfg.get_settings.cache_clear()
    p = RedditProvider()
    cfg.get_settings.cache_clear()
    monkeypatch.undo()

    result = await p.search("asyncio", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "reddit"
    assert result.results[0].title == "Async Python: asyncio for beginners"


@pytest.mark.asyncio
async def test_search_raises_on_api_error(respx_mock) -> None:
    import respx

    respx_mock.post("https://www.reddit.com/api/v1/access_token").mock(
        return_value=respx.MockResponse(200, json={"access_token": "tok123"}),
    )
    respx_mock.get("https://oauth.reddit.com/search.json").mock(
        return_value=respx.MockResponse(503, json={}),
    )

    import metasearchmcp.config as cfg

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("REDDIT_CLIENT_ID", "cid")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "csecret")
    cfg.get_settings.cache_clear()
    p = RedditProvider()
    cfg.get_settings.cache_clear()
    monkeypatch.undo()

    with pytest.raises(HTTPStatusError):
        await p.search("asyncio", SearchParams(num_results=5))
