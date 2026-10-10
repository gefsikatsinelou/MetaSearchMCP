"""Unit tests for the Jobicy remote-job provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.jobicy import JobicyProvider

_API_URL = "https://jobicy.com/api/v2/remote-jobs"

_JOBS_RESPONSE: dict[str, object] = {
    "apiVersion": "2.2.19",
    "jobCount": 3,
    "hasMore": True,
    "jobs": [
        # Body-only match: "python" appears in the excerpt, not the title.
        {
            "id": 152000,
            "url": "https://jobicy.com/jobs/152000-office-assistant",
            "jobSlug": "152000-office-assistant",
            "jobTitle": "Remote Office Assistant",
            "companyName": "Coalition Technologies",
            "jobIndustry": ["Admin"],
            "jobType": ["Full-Time"],
            "jobGeo": "Anywhere",
            "jobLevel": "Junior",
            "jobExcerpt": "<p>Some light <b>Python</b> scripting.</p>",
            "pubDate": "2026-09-11T20:16:48+00:00",
            "companyLogo": "https://jobicy.com/data/logo.jpg",
        },
        # Title matches the query -> must be ranked first.
        {
            "id": 152955,
            "url": "https://jobicy.com/jobs/152955-partner-solutions-architect",
            "jobSlug": "152955-partner-solutions-architect",
            "jobTitle": "Senior Python Engineer",
            "companyName": "Datadog",
            "jobIndustry": ["Software Development"],
            "jobType": ["Full-Time", "Remote"],
            "jobGeo": "Germany, UK",
            "jobLevel": "Senior",
            "salaryMin": 100000,
            "salaryMax": 150000,
            "salaryCurrency": "USD",
            "salaryPeriod": "Yearly",
            "jobExcerpt": "<p>Build &amp; ship backend services.</p>",
            "pubDate": "2026-10-10T05:10:17+00:00",
        },
        # No url / no title -> skipped.
        {"id": 5, "jobTitle": "", "url": "https://jobicy.com/jobs/5"},
        {"id": 6, "jobTitle": "Nameless", "url": ""},
        "junk",
        None,
    ],
}


def _provider() -> JobicyProvider:
    return JobicyProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "jobicy"
    assert p.tags == ["jobs", "career", "remote", "web"]
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "jobicy" in registry
    assert registry["jobicy"].tags == ["jobs", "career", "remote", "web"]


def test_plain_text_strips_markup_and_entities() -> None:
    assert JobicyProvider._plain_text("<p>Hello <b>World</b></p>") == "Hello World"
    assert JobicyProvider._plain_text("Build &amp; ship") == "Build & ship"
    assert JobicyProvider._plain_text(None) == ""
    assert JobicyProvider._plain_text("   ") == ""


def test_string_list_normalizes_values() -> None:
    assert JobicyProvider._string_list(["Full-Time", " Remote ", ""]) == [
        "Full-Time",
        "Remote",
    ]
    assert JobicyProvider._string_list("Full-Time") == ["Full-Time"]
    assert JobicyProvider._string_list(None) == []


def test_salary_composition() -> None:
    full = JobicyProvider._salary(
        {
            "salaryMin": 100000,
            "salaryMax": 150000,
            "salaryCurrency": "USD",
            "salaryPeriod": "Yearly",
        },
    )
    assert full == "100000-150000 USD / Yearly"
    assert JobicyProvider._salary({"salaryMin": 90000}) == "90000"
    assert JobicyProvider._salary({}) == ""


def test_tokens_and_title_score() -> None:
    tokens = JobicyProvider._tokens("Senior Python Engineer!")
    assert tokens == ["senior", "python", "engineer"]
    assert JobicyProvider._title_score("Senior Python Engineer", tokens) == 3
    assert JobicyProvider._title_score("Remote Office Assistant", tokens) == 0
    assert JobicyProvider._title_score("Senior Python Engineer", []) == 0


def test_parse_jobs_ranks_title_matches_first() -> None:
    result = _provider()._parse_jobs(_JOBS_RESPONSE, limit=10, query="python engineer")

    assert [r.title for r in result.results] == [
        "Senior Python Engineer",
        "Remote Office Assistant",
    ]
    first = result.results[0]
    assert first.rank == 1
    assert first.url.endswith("partner-solutions-architect")
    assert first.source == "jobicy.com"
    assert first.provider == "jobicy"
    assert first.published_date == "2026-10-10"
    assert "Datadog" in first.snippet
    assert "Salary: 100000-150000 USD / Yearly" in first.snippet
    assert "Full-Time, Remote" in first.snippet
    assert "Senior" in first.snippet
    assert "Industry: Software Development" in first.snippet
    assert "Build & ship backend services." in first.snippet
    assert first.extra["job_id"] == "152955"
    assert first.extra["company"] == "Datadog"
    assert first.extra["location"] == "Germany, UK"
    assert first.extra["level"] == "Senior"
    assert first.extra["job_types"] == ["Full-Time", "Remote"]
    assert first.extra["publication_date"] == "2026-10-10T05:10:17+00:00"

    second = result.results[1]
    assert second.rank == 2
    assert "Coalition Technologies" in second.snippet
    assert "Some light Python scripting." in second.snippet
    assert "<p>" not in second.snippet
    assert second.extra["salary"] is None


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
                "url": "https://jobicy.com/jobs/1",
                "jobTitle": "Long Posting",
                "jobExcerpt": "word " * 200,
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
    assert params["tag"] == "python engineer"
    assert params["count"] == "12"


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
