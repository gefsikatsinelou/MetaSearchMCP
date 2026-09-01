"""openFDA drug approval search via the keyless public API.

``GET https://api.fda.gov/drug/drugsfda.json?search=QUERY&limit=N`` returns
drug approval applications from the openFDA dataset, which aggregates
structured data from the U.S. Food and Drug Administration. No API key or
authentication is required (the public endpoint is rate-limited per IP).

Each hit is a drug application with its application number, sponsor name,
marketing status, submission history, and associated products (brand name,
active ingredients, dosage form, and route of administration). The provider
is keyless, uses only the shared httpx client, and tags itself
``drugs``/``pharma``/``medical`` so it complements the existing ChEMBL
provider in biomedical searches.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.fda.gov/drug/drugsfda.json"
# openFDA caps a single request at 100 results; keep well below that.
_MAX_API_RESULTS = 50


class OpenFDADrugProvider(BaseProvider):
    """Search FDA drug approval applications via the keyless openFDA API.

    Keyless. Uses the public drugs/drugsfda.json endpoint (``?search=QUERY``)
    to find approved drug applications. Each hit carries the application
    number, sponsor name, products (brand name, active ingredients, dosage
    form, route), and approval/submission status.
    """

    name = "openfda"
    description = (
        "Search FDA drug approval applications — sponsor, active ingredients, "
        "dosage form, and approval status via the keyless openFDA API."
    )
    tags: ClassVar[list[str]] = ["drugs", "pharma", "medical", "bio", "web"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _submission_summary(submissions: Any) -> dict[str, Any]:
        """Summarize the newest submission for an application.

        Returns a dict with the latest submission's type, status, and date
        (as a YYYY-MM-DD string), or an empty dict when no usable submission
        exists.
        """
        if not isinstance(submissions, list):
            return {}
        for submission in submissions:
            if not isinstance(submission, dict):
                continue
            status = (submission.get("submission_status") or "").upper()
            if status != "AP":
                continue
            raw_date = submission.get("submission_status_date") or ""
            date_prefix = (
                f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
                if len(raw_date) >= 8 and raw_date.isdigit()
                else (raw_date or None)
            )
            return {
                "submission_type": submission.get("submission_type"),
                "submission_status": status,
                "submission_date": date_prefix,
            }
        return {}

    def _parse(self, data: Any, limit: int | None = None) -> ProviderResult:
        """Parse the drugs/drugsfda.json response into structured results.

        The response is an object with a ``results`` list; each element is
        one drug application. Non-dict entries and applications without an
        application number or any product are skipped.
        """
        results: list[SearchResult] = []
        max_results = limit or self._max_results
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        applications = data.get("results")
        if not isinstance(applications, list):
            return ProviderResult(results=results)

        for item in applications:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue

            app_number = self._clean(item.get("application_number"))
            products = item.get("products")
            if not app_number or not isinstance(products, list) or not products:
                continue

            products = [p for p in products if isinstance(p, dict)]
            if not products:
                continue

            first = products[0]
            title = self._clean(first.get("brand_name"))
            if not title:
                title = " / ".join(
                    self._clean(i.get("name"))
                    for i in (first.get("active_ingredients") or [])
                    if isinstance(i, dict)
                )
            if not title:
                continue

            sponsor = self._clean(item.get("sponsor_name"))
            # Default to the newest application-approval status on record.
            submission = self._submission_summary(item.get("submissions"))
            approval_date = submission.get("submission_date")

            ingredients: list[str] = []
            for ingredient in first.get("active_ingredients") or []:
                if not isinstance(ingredient, dict):
                    continue
                name = self._clean(ingredient.get("name"))
                strength = self._clean(ingredient.get("strength"))
                if name:
                    ingredients.append(f"{name} {strength}".strip())

            dosage_form = self._clean(first.get("dosage_form"))
            route = self._clean(first.get("route"))
            marketing_status = self._clean(first.get("marketing_status"))

            snippet_parts: list[str] = []
            if sponsor:
                snippet_parts.append(sponsor)
            if ingredients:
                snippet_parts.append(f"Active: {'; '.join(ingredients[:3])}")
            if dosage_form:
                snippet_parts.append(dosage_form)
            if route:
                snippet_parts.append(route)
            if approval_date:
                snippet_parts.append(f"Approved: {approval_date}")
            if marketing_status:
                snippet_parts.append(marketing_status)

            results.append(
                SearchResult(
                    title=title,
                    url=(
                        "https://www.accessdata.fda.gov/scripts/cder/daf/"
                        f"index.cfm?event=overview.process&ApplNo={app_number}"
                    ),
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source="open.fda.gov",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=approval_date,
                    extra={
                        "application_number": app_number,
                        "sponsor": sponsor,
                        "active_ingredients": ingredients,
                        "dosage_form": dosage_form,
                        "route": route,
                        "marketing_status": marketing_status,
                        "submission_type": submission.get("submission_type"),
                        "submission_status": submission.get("submission_status"),
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search openFDA for drug applications matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(_API_URL, params={"search": query, "limit": limit})
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit)
