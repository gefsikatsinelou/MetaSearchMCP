"""Search DailyMed — the NLM repository of FDA drug labels — for SPL documents.

``dailymed.nlm.nih.gov`` is the U.S. National Library of Medicine's official
repository of Structured Product Labeling (SPL) documents: the current FDA
labeling for prescription and over-the-counter drugs.  Its keyless public
Content Service exposes a drug-name search endpoint::

    GET https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json
        ?drug_name=QUERY&pagesize=N

The response is ``{"data": [{"spl_version": ..., "published_date": ...,
"title": ..., "setid": ...}], "metadata": {...}}``.  Each hit is one SPL
document carrying a stable ``setid`` (the label's permanent identifier), a
human-readable ``title`` of the form ``BRAND (INGREDIENTS) FORM [LABELER]``,
the SPL ``spl_version`` and the document's ``published_date``.

This complements the openFDA provider — which covers approval *applications* —
by surfacing the actual marketed labeling documents.  No API key is required.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json"
# Canonical detail page for a stable SPL setid.
_DETAIL_URL = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid="
# The service caps a single response at 100 SPL documents.
_MAX_API_RESULTS = 100

# ``TITLE`` embeds the labeler in a trailing ``[...]`` and the active
# ingredients / brand in a leading ``(...)``: "BRAND (ING) FORM [LABELER]".
_LABELER_RE = re.compile(r"\[([^\]]+)\]\s*$")
_INGREDIENTS_RE = re.compile(r"\(([^)]*)\)")


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _iso_date(value: object) -> str | None:
    """Convert a DailyMed ``published_date`` (e.g. ``Oct 02, 2026``) to ISO."""
    text = _clean(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%b %d, %Y").date().isoformat()
    except ValueError:
        return None


class DailyMedProvider(BaseProvider):
    """Search FDA drug labels (Structured Product Labeling) in DailyMed.

    Keyless.  Issues a single request against the DailyMed Content Service
    ``spls.json`` drug-name search and returns one hit per matching SPL
    document, carrying the stable setid, brand/ingredient title, labeler,
    SPL version and publication date, linking to the label page on DailyMed.
    """

    name = "dailymed"
    description = (
        "Search DailyMed — the NLM repository of FDA drug labels — for "
        "Structured Product Labeling documents (brand, active ingredients, "
        "labeler, SPL version and publication date) via the keyless DailyMed "
        "Content Service, no API key required."
    )
    tags: ClassVar[list[str]] = ["drugs", "pharma", "medical", "health", "web"]

    @staticmethod
    def _labeler(title: str) -> str:
        """Extract the trailing ``[LABELER]`` from an SPL title, if present."""
        match = _LABELER_RE.search(title)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _ingredients(title: str) -> str:
        """Extract the leading ``(INGREDIENTS)`` from an SPL title, if present."""
        match = _INGREDIENTS_RE.search(title)
        return match.group(1).strip() if match else ""

    def _snippet(
        self,
        ingredients: str,
        labeler: str,
        version: object,
        published: str | None,
    ) -> str:
        """Compose the snippet for a single DailyMed SPL document."""
        parts: list[str] = []
        if ingredients:
            parts.append(f"Ingredients: {ingredients}")
        if labeler:
            parts.append(f"Labeler: {labeler}")
        if version is not None:
            parts.append(f"SPL version: {version}")
        if published:
            parts.append(f"Published: {published}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(self, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw DailyMed SPL entry."""
        setid = _clean(item.get("setid"))
        title = _clean(item.get("title"))
        if not setid or not title:
            return None

        labeler = self._labeler(title)
        ingredients = self._ingredients(title)
        published = _iso_date(item.get("published_date"))
        version = item.get("spl_version")

        return SearchResult(
            title=title,
            url=f"{_DETAIL_URL}{quote(setid)}",
            snippet=self._snippet(ingredients, labeler, version, published),
            source="dailymed.nlm.nih.gov",
            rank=rank,
            provider=self.name,
            published_date=published,
            extra={
                "setid": setid,
                "spl_version": version,
                "labeler": labeler or None,
                "ingredients": ingredients or None,
                "published_date_raw": _clean(item.get("published_date")) or None,
            },
        )

    def _parse(self, data: object, limit: int) -> list[SearchResult]:
        """Parse a DailyMed ``spls.json`` response, deduplicating by setid."""
        if not isinstance(data, dict):
            return []
        items = data.get("data")
        if not isinstance(items, list):
            return []

        results: list[SearchResult] = []
        seen: set[str] = set()
        for item in items:
            if len(results) >= limit:
                break
            if not isinstance(item, dict):
                continue
            setid = _clean(item.get("setid"))
            if not setid or setid in seen:
                continue
            seen.add(setid)
            built = self._build_result(item, len(results) + 1)
            if built is None:
                continue
            results.append(built)
        return results

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search DailyMed for drug labels matching *query*.

        A blank query performs no request.  DailyMed ranks matches by its own
        relevance order, which is preserved in the returned results.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={"drug_name": cleaned, "pagesize": limit},
            )
            resp.raise_for_status()
            data = resp.json()

        return ProviderResult(results=self._parse(data, limit))
