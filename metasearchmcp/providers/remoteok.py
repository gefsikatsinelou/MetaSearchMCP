"""RemoteOK remote developer jobs search via the public, keyless API.

RemoteOK (remoteok.com) is a job board focused exclusively on remote
developer and tech positions. Its public JSON API requires no API key
and accepts a ``?tag=`` filter for technology keywords:

``GET https://remoteok.com/api?tag=QUERY``

Each hit carries the position title, company name, location/compensation
summary, tags, job type, and the original posting URL. The provider is
keyless, uses only the shared httpx client, and tags itself
``jobs``/``career`` so it can be filtered from the generic web pool.

Note: the RemoteOK API endpoint occasionally returns HTML (rate limit or
maintenance pages) instead of JSON; the provider treats such responses as
an empty result set rather than crashing the aggregate search.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://remoteok.com/api"
# The API returns the whole feed; the shared per-provider result cap applies.
_MAX_API_RESULTS = 50


class RemoteOKProvider(BaseProvider):
    """Search remote developer jobs on RemoteOK.

    Keyless. Uses the public RemoteOK JSON API (``?tag=QUERY``) to find
    remote developer positions. Each hit carries the job title, company,
    location/compensation summary, tags, job type, and posting URL.
    """

    name = "remoteok"
    description = (
        "Search remote developer jobs on RemoteOK — title, company, "
        "salary/location summary, and tags via the keyless public API."
    )
    tags: ClassVar[list[str]] = ["jobs", "career", "web"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    def _parse(self, data: Any, limit: int | None = None) -> ProviderResult:
        """Parse the RemoteOK /api response into structured results.

        The response is a JSON array of job objects; the first element is a
        metadata placeholder (``{"success": true}``), and every other element
        describes one job posting.
        """
        results: list[SearchResult] = []
        max_results = limit or self._max_results
        if not isinstance(data, list) or not data:
            return ProviderResult(results=results)

        for i, item in enumerate(data, start=1):
            if i > max_results + 1:  # account for the metadata placeholder
                break
            if not isinstance(item, dict):
                continue
            if "id" not in item or "title" not in item:
                # Skip the leading placeholder and any other non-job entries.
                continue

            title = self._clean(item.get("title"))
            if not title:
                continue

            company = self._clean(item.get("company"))
            location = self._clean(item.get("location"))
            tags = [
                str(tag).strip() for tag in (item.get("tags") or []) if str(tag).strip()
            ]
            job_type = self._clean(item.get("type"))
            salary = self._clean(item.get("salary"))

            snippet_parts: list[str] = []
            if company:
                snippet_parts.append(company)
            if location:
                snippet_parts.append(location)
            if salary:
                snippet_parts.append(salary)
            if tags:
                snippet_parts.append(f"Tags: {', '.join(tags[:6])}")
            if job_type:
                snippet_parts.append(job_type)

            results.append(
                SearchResult(
                    title=title,
                    url=str(item.get("url") or ""),
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source="remoteok.com",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "company": company,
                        "location": location,
                        "salary": salary,
                        "tags": tags,
                        "job_type": job_type,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search RemoteOK for remote jobs matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(_API_URL, params={"tag": query})
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit)
