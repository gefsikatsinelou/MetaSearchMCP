"""Jobicy remote-job search via the keyless public API.

Jobicy (jobicy.com) is a remote-first job board that exposes a documented,
keyless JSON API.  A single endpoint is used:

* ``GET https://jobicy.com/api/v2/remote-jobs?count=N&tag=QUERY`` — free-text
  search across remote postings.  Each hit carries the job title, the company,
  the industry, the job type, the candidate location, the seniority level, an
  optional salary range, a publication date and an HTML excerpt.

The search term is sent as the ``tag`` parameter (Jobicy's free-text filter).
Because the API orders hits by its own ranking, postings whose *title* matches
more of the queried terms are re-ordered to the front, keeping the response
stable for equally-relevant postings.  This complements
:mod:`metasearchmcp.providers.remoteok` (a developer-focused tag feed) and
:mod:`metasearchmcp.providers.remotive` (another keyword-searchable remote
index) with a third, independent remote-job source.
"""

from __future__ import annotations

import html
import re
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://jobicy.com/api/v2/remote-jobs"
# Jobicy caps how many postings it returns per call; keep pages small for agents.
_MAX_API_RESULTS = 50
# Oversample postings so that re-ranking by title match still fills a page.
_RANK_OVERSAMPLE = 3
# Characters of the posting excerpt copied into the snippet.
_SNIPPET_EXCERPT_LENGTH = 160

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WORD_RE = re.compile(r"[a-z0-9]+")


class JobicyProvider(BaseProvider):
    """Search remote jobs advertised on Jobicy.

    Keyless. Uses the public Jobicy JSON API (``?tag=QUERY``) to find remote
    positions.  Each hit carries the job title, company, industry, job type,
    location, seniority level and salary range, and results are ordered so
    that title matches lead the page.
    """

    name = "jobicy"
    description = (
        "Search remote jobs on Jobicy — title, company, industry and salary "
        "via the keyless public API."
    )
    tags: ClassVar[list[str]] = ["jobs", "career", "remote", "web"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @classmethod
    def _plain_text(cls, value: object) -> str:
        """Strip HTML markup and entities from a description field."""
        raw = cls._clean(value)
        if not raw:
            return ""
        return cls._clean(html.unescape(_HTML_TAG_RE.sub(" ", raw)))

    @classmethod
    def _string_list(cls, value: object) -> list[str]:
        """Return a list of non-empty, whitespace-collapsed strings."""
        raw = value if isinstance(value, list) else [value]
        return [item for item in (cls._clean(v) for v in raw) if item]

    @staticmethod
    def _tokens(query: str) -> list[str]:
        """Return the lowercase alphanumeric tokens of *query*."""
        return _WORD_RE.findall(query.lower())

    @classmethod
    def _title_score(cls, title: str, tokens: list[str]) -> int:
        """Count how many query *tokens* appear in *title*."""
        lowered = title.lower()
        return sum(1 for token in tokens if token in lowered)

    @classmethod
    def _salary(cls, item: dict[str, Any]) -> str:
        """Compose a human-readable salary range from the raw salary fields."""
        low = cls._clean(item.get("salaryMin"))
        high = cls._clean(item.get("salaryMax"))
        currency = cls._clean(item.get("salaryCurrency"))
        period = cls._clean(item.get("salaryPeriod"))
        if not low and not high:
            return ""
        parts = [f"{low}-{high}" if low and high else (low or high)]
        if currency:
            parts.append(currency)
        if period:
            parts.append(f"/ {period}")
        return " ".join(parts)

    def _build_result(self, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw posting entry."""
        title = self._clean(item.get("jobTitle"))
        url = self._clean(item.get("url"))
        if not title or not url:
            return None

        job_id = self._clean(item.get("id"))
        company = self._clean(item.get("companyName"))
        industries = self._string_list(item.get("jobIndustry"))
        job_types = self._string_list(item.get("jobType"))
        location = self._clean(item.get("jobGeo"))
        level = self._clean(item.get("jobLevel"))
        salary = self._salary(item)
        publication_date = self._clean(item.get("pubDate"))
        published_date = self._iso_date_prefix(publication_date)
        excerpt = self._plain_text(item.get("jobExcerpt"))

        snippet_parts: list[str] = []
        if company:
            snippet_parts.append(company)
        if location:
            snippet_parts.append(location)
        if salary:
            snippet_parts.append(f"Salary: {salary}")
        if job_types:
            snippet_parts.append(", ".join(job_types))
        if level:
            snippet_parts.append(level)
        if industries:
            snippet_parts.append(f"Industry: {', '.join(industries)}")
        if excerpt:
            snippet_parts.append(excerpt[:_SNIPPET_EXCERPT_LENGTH])

        return SearchResult(
            title=title,
            url=url,
            snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
            source="jobicy.com",
            rank=rank,
            provider=self.name,
            published_date=published_date,
            extra={
                "job_id": job_id or None,
                "company": company or None,
                "industries": industries,
                "job_types": job_types,
                "location": location or None,
                "level": level or None,
                "salary": salary or None,
                "publication_date": publication_date or None,
                "job_slug": self._clean(item.get("jobSlug")) or None,
                "company_logo": self._clean(item.get("companyLogo")) or None,
            },
        )

    def _parse_jobs(self, data: object, limit: int, query: str) -> ProviderResult:
        """Parse a Jobicy response, ranking title matches first.

        The relevance score is the number of query tokens found in a posting
        title; the sort is stable, so postings with the same score keep the
        order Jobicy returned them in.  Because the re-ranking can promote a
        posting to the front of the page, postings are collected up to an
        oversampled cap before the page is cut to *limit*.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        jobs = data.get("jobs")
        if not isinstance(jobs, list):
            return ProviderResult(results=results)

        oversample = min(limit * _RANK_OVERSAMPLE, _MAX_API_RESULTS)
        tokens = self._tokens(query)
        scored: list[tuple[int, SearchResult]] = []
        for item in jobs:
            if not isinstance(item, dict):
                continue
            result = self._build_result(item, rank=len(scored) + 1)
            if result is None:
                continue
            scored.append((self._title_score(result.title, tokens), result))
            if len(scored) >= oversample:
                break

        scored.sort(key=lambda pair: pair[0], reverse=True)
        for rank, (_, result) in enumerate(scored[:limit], start=1):
            result.rank = rank
            results.append(result)
        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Jobicy for remote jobs matching *query*."""
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        count = min(limit * _RANK_OVERSAMPLE, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={"count": count, "tag": cleaned},
            )
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError:
                # Jobicy occasionally answers with a non-JSON error page.
                return ProviderResult(results=[])

        return self._parse_jobs(data, limit, cleaned)
