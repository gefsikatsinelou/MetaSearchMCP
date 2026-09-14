"""Remotive remote-job search via the keyless public API.

Remotive (remotive.com) is a remote-only job board with a documented,
keyless JSON API.  A single endpoint is used:

* ``GET https://remotive.com/api/remote-jobs?search=QUERY`` — free-text
  search across remote job postings.  Each hit carries the job title, the
  company, the category, the tags, the job type, the required candidate
  location, a salary range, the publication date and an HTML description.

Remotive matches the query against the whole posting body, so the raw feed
often leads with roles whose description merely mentions the term.  Results
are therefore re-ordered locally: postings whose *title* contains more of
the queried terms rank first, while equally-relevant postings keep the
order the API returned.  This complements
:mod:`metasearchmcp.providers.remoteok` (a developer-focused tag feed) with
a broader, keyword-searchable remote job index.
"""

from __future__ import annotations

import html
import re
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://remotive.com/api/remote-jobs"
# Remotive caps how many postings it returns per call; keep pages small for agents.
_MAX_API_RESULTS = 50
# Oversample postings so that re-ranking by title match still fills a page.
_RANK_OVERSAMPLE = 3
# Number of posting tags surfaced in a snippet before truncation.
_SNIPPET_TAG_LIMIT = 6
# Characters of the posting description copied into the snippet.
_SNIPPET_DESCRIPTION_LENGTH = 160

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WORD_RE = re.compile(r"[a-z0-9]+")


class RemotiveProvider(BaseProvider):
    """Search remote jobs advertised on Remotive.

    Keyless. Uses the public Remotive JSON API (``?search=QUERY``) to find
    remote positions.  Each hit carries the job title, company, category,
    tags, job type, required location, salary range and posting URL, and
    results are ordered so that title matches lead the page.
    """

    name = "remotive"
    description = (
        "Search remote jobs on Remotive — title, company, category, salary "
        "and required location via the keyless public API."
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
    def _tags(cls, value: object) -> list[str]:
        """Return the posting tags as a list of non-empty strings."""
        if not isinstance(value, list):
            return []
        return [tag for tag in (cls._clean(item) for item in value) if tag]

    def _snippet(
        self,
        company: str,
        location: str,
        salary: str,
        job_type: str,
        category: str,
        tags: list[str],
        description: str,
    ) -> str:
        """Compose the snippet for a single posting."""
        parts: list[str] = []
        if company:
            parts.append(company)
        if location:
            parts.append(location)
        if salary:
            parts.append(f"Salary: {salary}")
        if job_type:
            parts.append(job_type.replace("_", " "))
        if category:
            parts.append(category)
        if tags:
            parts.append(f"Tags: {', '.join(tags[:_SNIPPET_TAG_LIMIT])}")
        if description:
            parts.append(description[:_SNIPPET_DESCRIPTION_LENGTH])
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(self, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw posting entry."""
        title = self._clean(item.get("title"))
        url = self._clean(item.get("url"))
        if not title or not url:
            return None

        job_id = self._clean(item.get("id"))
        company = self._clean(item.get("company_name"))
        category = self._clean(item.get("category"))
        job_type = self._clean(item.get("job_type"))
        location = self._clean(item.get("candidate_required_location"))
        salary = self._clean(item.get("salary"))
        tags = self._tags(item.get("tags"))
        publication_date = self._clean(item.get("publication_date"))
        published_date = self._iso_date_prefix(publication_date)
        description = self._plain_text(item.get("description"))

        return SearchResult(
            title=title,
            url=url,
            snippet=self._snippet(
                company,
                location,
                salary,
                job_type,
                category,
                tags,
                description,
            ),
            source="remotive.com",
            rank=rank,
            provider=self.name,
            published_date=published_date,
            extra={
                "job_id": job_id or None,
                "company": company or None,
                "category": category or None,
                "job_type": job_type or None,
                "location": location or None,
                "salary": salary or None,
                "tags": tags,
                "publication_date": publication_date or None,
                "company_logo": self._clean(item.get("company_logo")) or None,
            },
        )

    def _parse_jobs(self, data: object, limit: int, query: str) -> ProviderResult:
        """Parse a jobs response, ranking title matches first.

        The API score is the number of query tokens found in a posting title;
        the sort is stable, so postings with the same score keep the order
        Remotive returned them in.  Because the re-ranking can move a posting
        to the front of the page, postings are collected up to an oversampled
        cap before the page is cut to *limit*.
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
        """Search Remotive for remote jobs matching *query*."""
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={"search": cleaned, "limit": limit},
            )
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError:
                # Remotive occasionally answers with an HTML maintenance page.
                return ProviderResult(results=[])

        return self._parse_jobs(data, limit, cleaned)
