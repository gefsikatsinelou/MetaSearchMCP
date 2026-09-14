"""Unit tests for the Remotive remote-job provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.remotive import RemotiveProvider

_API_URL = "https://remotive.com/api/remote-jobs"

_JOBS_RESPONSE: dict[str, object] = {
    "00-warning": "thanks for using the API",
    "job-count": 3,
    "total-job-count": 3,
    "jobs": [
        # Body-only match: "python" appears in the description, not the title.
        {
            "id": 1680495,
            "url": "https://remotive.com/remote-jobs/marketing/office-assistant-1680495",
            "title": "Remote Office Assistant",
            "company_name": "Coalition Technologies ",
            "category": "Marketing",
            "tags": ["css", "excel", "", "php"],
            "job_type": "full_time",
            "publication_date": "2026-09-11T20:16:48",
            "candidate_required_location": "Worldwide",
            "salary": "$31,2k- $52k",
            "description": "<p>Some light <b>Python</b> scripting.</p>",
            "company_logo": "https://remotive.com/job/1680495/logo",
        },
        # Title matches the query -> must be ranked first.
        {
            "id": 2091126,
            "url": "https://remotive.com/remote-jobs/software-dev/python-engineer-2091126",
            "title": "Senior Python Engineer",
            "company_name": "iMerit Technology",
            "category": "Software Development",
            "tags": ["AI/ML", "research"],
            "job_type": "contract",
            "publication_date": "2026-09-11T06:49:00",
            "candidate_required_location": "France, Japan",
            "salary": "$100K-$120K",
            "description": "<p>Build &amp; ship backend services.</p>",
        },
        # No url / no title -> skipped.
        {"id": 5, "title": "", "url": "https://remotive.com/jobs/5"},
        {"id": 6, "title": "Nameless", "url": ""},
        "junk",
        None,
    ],
}


def _provider() -> RemotiveProvider:
    return RemotiveProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "remotive"
    assert p.tags == ["jobs", "career", "remote", "web"]
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "remotive" in registry
    assert registry["remotive"].tags == ["jobs", "career", "remote", "web"]


def test_plain_text_strips_markup_and_entities() -> None:
    assert RemotiveProvider._plain_text("<p>Hello <b>World</b></p>") == "Hello World"
    assert RemotiveProvider._plain_text("Build &amp; ship") == "Build & ship"
    assert RemotiveProvider._plain_text(None) == ""
    assert RemotiveProvider._plain_text("   ") == ""


def test_tokens_and_title_score() -> None:
    tokens = RemotiveProvider._tokens("Senior Python Engineer!")
    assert tokens == ["senior", "python", "engineer"]
    assert RemotiveProvider._title_score("Senior Python Engineer", tokens) == 3
    assert RemotiveProvider._title_score("Remote Office Assistant", tokens) == 0
    assert RemotiveProvider._title_score("Senior Python Engineer", []) == 0


def test_parse_jobs_ranks_title_matches_first() -> None:
    result = _provider()._parse_jobs(_JOBS_RESPONSE, limit=10, query="python engineer")

    assert [r.title for r in result.results] == [
        "Senior Python Engineer",
        "Remote Office Assistant",
    ]
    first = result.results[0]
    assert first.rank == 1
    assert first.url.endswith("python-engineer-2091126")
    assert first.source == "remotive.com"
    assert first.provider == "remotive"
    assert first.published_date == "2026-09-11"
    assert "iMerit Technology" in first.snippet
    assert "Salary: $100K-$120K" in first.snippet
    assert "contract" in first.snippet
    assert "Software Development" in first.snippet
    assert "Tags: AI/ML, research" in first.snippet
    assert "Build & ship backend services." in first.snippet
    assert first.extra["job_id"] == "2091126"
    assert first.extra["company"] == "iMerit Technology"
    assert first.extra["location"] == "France, Japan"
    assert first.extra["job_type"] == "contract"
    assert first.extra["publication_date"] == "2026-09-11T06:49:00"
    assert first.extra["tags"] == ["AI/ML", "research"]

    second = result.results[1]
    assert second.rank == 2
    assert "Coalition Technologies" in second.snippet
    assert second.extra["company"] == "Coalition Technologies"
    # Empty tags are dropped, text is stripped and markup removed.
    assert second.extra["tags"] == ["css", "excel", "php"]
    assert "Some light Python scripting." in second.snippet
    assert "<p>" not in second.snippet


def test_parse_jobs_handles_junk_and_limits() -> None:
    assert _provider()._parse_jobs("junk", limit=5, query="python").results == []
    assert _provider()._parse_jobs({}, limit=5, query="python").results == []
    assert (
        _provider()._parse_jobs({"jobs": "junk"}, limit=5, query="python").results == []
    )

    limited = _provider()._parse_jobs(_JOBS_RESPONSE, limit=1, query="python")
    assert len(limited.results) == 1
    # Only the single highest-scoring posting is kept.
    assert limited.results[0].title == "Senior Python Engineer"


def test_snippet_is_truncated_to_shared_limit() -> None:
    data = {
        "jobs": [
            {
                "id": 1,
                "url": "https://remotive.com/jobs/1",
                "title": "Long Posting",
                "description": "word " * 200,
            },
        ],
    }
    result = _provider()._parse_jobs(data, limit=5, query="long")
    snippet = result.results[0].snippet
    assert len(snippet) <= 400
    assert snippet.startswith("word word")


@pytest.mark.asyncio
async def test_search_sends_query_and_limit(respx_mock) -> None:
    import respx

    route = respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_JOBS_RESPONSE),
    )

    result = await _provider().search("python engineer", SearchParams(num_results=4))

    assert [r.title for r in result.results] == [
        "Senior Python Engineer",
        "Remote Office Assistant",
    ]
    params = route.calls[0].request.url.params
    assert params["search"] == "python engineer"
    assert params["limit"] == "4"


@pytest.mark.asyncio
async def test_search_with_blank_query_returns_empty(respx_mock) -> None:
    import respx

    route = respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(200, json=_JOBS_RESPONSE),
    )

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_tolerates_non_json_response(respx_mock) -> None:
    import respx

    respx_mock.get(_API_URL).mock(
        return_value=respx.MockResponse(
            200,
            text="<html><body>maintenance</body></html>",
            headers={"Content-Type": "text/html"},
        ),
    )

    result = await _provider().search("python", SearchParams(num_results=5))

    assert result.results == []
