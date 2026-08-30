"""Unit tests for the RemoteOK remote jobs search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.remoteok import RemoteOKProvider

# The first element of the RemoteOK response is a metadata placeholder.
_SAMPLE_RESPONSE: list[dict[str, object]] = [
    {"success": True},
    {
        "id": "12345",
        "title": "Senior Python Developer",
        "company": "Acme Corp",
        "location": "Remote (Worldwide)",
        "salary": "$120k-$150k",
        "type": "full_time",
        "tags": ["python", "django", "aws"],
        "url": "https://remoteok.com/remote-jobs/senior-python-developer",
    },
    {
        "id": "67890",
        "title": "Frontend Engineer",
        "company": "Example Inc",
        "location": "Remote (US only)",
        "salary": "",
        "type": "contract",
        "tags": ["react", "typescript"],
        "url": "https://remoteok.com/remote-jobs/frontend-engineer",
    },
    {
        # Missing id -> skipped (placeholder-like entry).
        "title": "Not a real job",
        "company": "Junk",
    },
    {
        # Missing title -> skipped.
        "id": "99999",
        "company": "Junk",
    },
]

_EMPTY_RESPONSE: list[dict[str, object]] = []


def _provider() -> RemoteOKProvider:
    return RemoteOKProvider()


def test_remoteok_name_and_tags() -> None:
    p = _provider()
    assert p.name == "remoteok"
    assert p.tags == ["jobs", "career", "web"]


def test_parse_basic() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Senior Python Developer"
    assert r.url == "https://remoteok.com/remote-jobs/senior-python-developer"
    assert "Acme Corp" in r.snippet
    assert "Remote (Worldwide)" in r.snippet
    assert "$120k-$150k" in r.snippet
    assert "Tags: python, django, aws" in r.snippet
    assert r.provider == "remoteok"
    assert r.source == "remoteok.com"
    assert r.rank == 1
    assert r.extra["company"] == "Acme Corp"
    assert r.extra["location"] == "Remote (Worldwide)"
    assert r.extra["salary"] == "$120k-$150k"
    assert r.extra["tags"] == ["python", "django", "aws"]
    assert r.extra["job_type"] == "full_time"


def test_parse_second_job() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    r = result.results[1]
    assert r.title == "Frontend Engineer"
    assert r.rank == 2
    assert r.extra["job_type"] == "contract"
    assert r.extra["salary"] == ""


def test_parse_skips_placeholder_and_incomplete() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE)
    assert all(r.title and r.url for r in result.results)
    assert all(r.extra["company"] for r in result.results)


def test_parse_limit() -> None:
    result = _provider()._parse(_SAMPLE_RESPONSE, limit=1)
    assert len(result.results) == 1
    assert result.results[0].title == "Senior Python Developer"


def test_parse_empty_and_malformed() -> None:
    assert _provider()._parse(_EMPTY_RESPONSE).results == []
    assert _provider()._parse([]).results == []
    assert _provider()._parse([{"success": True}]).results == []
    assert _provider()._parse("junk").results == []
    assert _provider()._parse({"not": "a list"}).results == []
    assert _provider()._parse(None).results == []


def test_clean_text() -> None:
    assert RemoteOKProvider._clean("  a\n  b\t ") == "a b"
    assert RemoteOKProvider._clean(None) == ""
    assert RemoteOKProvider._clean("") == ""


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get("https://remoteok.com/api").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    p = _provider()
    result = await p.search("python", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "remoteok"
    request = respx_mock.calls.last.request
    assert request.url.params["tag"] == "python"


@pytest.mark.asyncio
async def test_search_empty_response(respx_mock) -> None:
    import respx

    respx_mock.get("https://remoteok.com/api").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_RESPONSE),
    )

    p = _provider()
    result = await p.search("zzz", SearchParams(num_results=5))
    assert result.results == []
