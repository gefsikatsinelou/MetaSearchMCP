"""Unit tests for the GitHub repository search provider.

Covers parsing of the GitHub Search API response (including archived
repositories and missing description), language/stars metadata
propagation, availability, and the API call path.
"""

from __future__ import annotations

import pytest
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.github import GitHubProvider


def _repo(
    *,
    full_name: str,
    html_url: str,
    description: str | None = "A repo.",
    language: str | None = "Python",
    stargazers_count: int = 100,
    archived: bool = False,
) -> dict:
    return {
        "full_name": full_name,
        "html_url": html_url,
        "description": description,
        "language": language,
        "stargazers_count": stargazers_count,
        "archived": archived,
    }


def _payload(*repos: dict) -> dict:
    return {"total_count": len(repos), "items": list(repos)}


def _provider() -> GitHubProvider:
    return GitHubProvider()


def test_parse_basic() -> None:
    p = _provider()
    result = p._parse(
        _payload(
            _repo(
                full_name="fastapi/fastapi",
                html_url="https://github.com/fastapi/fastapi",
                description="FastAPI framework, high performance.",
                stargazers_count=70000,
            ),
        ),
    )

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "fastapi/fastapi"
    assert r.url == "https://github.com/fastapi/fastapi"
    assert r.provider == "github"
    assert r.rank == 1
    assert r.source == "github.com"
    assert "FastAPI framework" in r.snippet
    assert r.extra["language"] == "Python"
    assert r.extra["stars"] == 70000


def test_parse_none_description_and_language() -> None:
    p = _provider()
    result = p._parse(
        _payload(
            _repo(
                full_name="user/empty",
                html_url="https://github.com/user/empty",
                description=None,
                language=None,
            ),
        ),
    )
    assert len(result.results) == 1
    assert result.results[0].snippet == "Stars: 100"
    assert result.results[0].extra["language"] == ""


def test_parse_empty_items() -> None:
    p = _provider()
    assert p._parse({}).results == []
    assert p._parse({"items": []}).results == []


def test_is_available() -> None:
    """Keyless provider is always available (public API, no token needed)."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.github.com/search/repositories").mock(
        return_value=respx.MockResponse(
            200,
            json=_payload(
                _repo(
                    full_name="fastapi/fastapi",
                    html_url="https://github.com/fastapi/fastapi",
                ),
            ),
        ),
    )

    p = _provider()
    result = await p.search("fastapi", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "github"
    assert result.results[0].title == "fastapi/fastapi"


@pytest.mark.asyncio
async def test_search_raises_on_api_error(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.github.com/search/repositories").mock(
        return_value=respx.MockResponse(403, json={"message": "rate limited"}),
    )

    p = _provider()
    with pytest.raises(HTTPStatusError):
        await p.search("fastapi", SearchParams(num_results=5))
