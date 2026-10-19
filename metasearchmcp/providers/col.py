"""Taxonomic name search via the keyless Catalogue of Life (ChecklistBank) API.

The `Catalogue of Life <https://www.catalogueoflife.org/>`_ (COL) is a global,
peer-reviewed index of the world's known species, assembled from hundreds of
authoritative taxonomic databases.  Its public search is served by ChecklistBank
and needs no API key::

    GET https://api.checklistbank.org/dataset/3LR/nameusage/search?q=QUERY

The response is a JSON object whose ``result`` array holds matching name usages.
Each carries the matched taxon ``id``, its scientific name, authorship, rank and
nomenclatural status (accepted/synonym), the full parent ``classification`` from
domain down to genus, the taxonomic ``group`` (e.g. ``chordates``) and any
``vernacularNames`` (common names).  Each result links to the taxon's page in the
COL portal.  No API key is required.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.checklistbank.org/dataset/3LR/nameusage/search"
# Canonical Catalogue of Life taxon page for a ChecklistBank usage id.
_TAXON_URL = "https://www.catalogueoflife.org/data/taxon"
# Upper bound on taxa surfaced for a single query.
_MAX_RESULTS = 25
# Main ranks used to build a compact ancestor lineage in the snippet.
_LINEAGE_RANKS = ("kingdom", "phylum", "class", "order", "family", "genus")


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if value is None:
        return ""
    return " ".join(str(value).split())


class ColProvider(BaseProvider):
    """Search scientific names in the Catalogue of Life.

    Keyless.  Uses the ChecklistBank ``nameusage/search`` endpoint for the COL
    checklist (dataset ``3LR``).  Each result is a name usage with its scientific
    name, authorship, rank, status, ancestor classification, taxonomic group and
    common names, linking to the taxon page.
    """

    name = "col"
    description = (
        "Search the Catalogue of Life — the global index of the world's known "
        "species — by scientific or common name, returning the matched taxon's "
        "scientific name, authorship, rank, status, full ancestor classification, "
        "taxonomic group and vernacular names; no API key required."
    )
    tags: ClassVar[list[str]] = ["biodiversity", "nature", "science"]

    def _lineage(self, classification: object) -> list[str]:
        """Return the ordered scientific names of the main ancestor ranks."""
        if not isinstance(classification, list):
            return []
        ranks = {
            _clean(entry.get("rank")).lower(): _clean(entry.get("name"))
            for entry in classification
            if isinstance(entry, dict) and _clean(entry.get("name"))
        }
        return [ranks[rank] for rank in _LINEAGE_RANKS if ranks.get(rank)]

    def _common_names(self, vernacular: object, limit: int = 3) -> list[str]:
        """Return up to *limit* de-duplicated common names, English first."""
        if not isinstance(vernacular, list):
            return []
        english: list[str] = []
        others: list[str] = []
        for entry in vernacular:
            if not isinstance(entry, dict):
                continue
            name = _clean(entry.get("name"))
            if not name:
                continue
            language = _clean(entry.get("language")).lower()
            (english if language.startswith("eng") else others).append(name)
        return list(dict.fromkeys(english + others))[:limit]

    def _taxon_result(self, item: object, rank: int) -> SearchResult | None:
        """Build one result from a single ChecklistBank name-usage record."""
        if not isinstance(item, dict):
            return None
        usage = item.get("usage")
        if not isinstance(usage, dict):
            return None
        name = usage.get("name")
        if not isinstance(name, dict):
            return None

        scientific_name = _clean(name.get("scientificName"))
        if not scientific_name:
            return None

        authorship = _clean(name.get("authorship"))
        title = _clean(usage.get("label")) or f"{scientific_name} {authorship}".strip()
        taxon_rank = _clean(name.get("rank"))
        status = _clean(usage.get("status"))
        group = _clean(item.get("group"))
        lineage = self._lineage(item.get("classification"))
        common_names = self._common_names(item.get("vernacularNames"))
        usage_id = _clean(item.get("id")) or _clean(usage.get("id"))

        snippet_parts: list[str] = []
        if taxon_rank:
            snippet_parts.append(taxon_rank)
        if status:
            snippet_parts.append(status)
        if group:
            snippet_parts.append(f"group: {group}")
        if lineage:
            snippet_parts.append(" > ".join(lineage))
        if common_names:
            snippet_parts.append("common: " + ", ".join(common_names))

        url = f"{_TAXON_URL}/{usage_id}" if usage_id else _TAXON_URL
        return SearchResult(
            title=title,
            url=url,
            snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
            source="catalogueoflife.org",
            provider=self.name,
            rank=rank,
            extra={
                "id": usage_id,
                "scientific_name": scientific_name,
                "authorship": authorship,
                "rank": taxon_rank,
                "status": status,
                "genus": _clean(name.get("genus")),
                "specific_epithet": _clean(name.get("specificEpithet")),
                "code": _clean(name.get("code")),
                "nom_status": _clean(name.get("nomStatus")),
                "group": group,
                "lineage": lineage,
                "common_names": common_names,
                "source_link": _clean(usage.get("link")),
            },
        )

    def _parse(self, payload: object, limit: int | None = None) -> ProviderResult:
        """Parse a ChecklistBank search response into structured results."""
        if not isinstance(payload, dict):
            return ProviderResult(results=[])
        items = payload.get("result")
        if not isinstance(items, list):
            return ProviderResult(results=[])

        max_results = limit or self._max_results
        results: list[SearchResult] = []
        for item in items:
            if len(results) >= max_results:
                break
            result = self._taxon_result(item, rank=len(results) + 1)
            if result is None:
                continue
            results.append(result)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the Catalogue of Life for taxa matching *query*."""
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_RESULTS)
        async with self._client() as client:
            resp = await client.get(_API_URL, params={"q": cleaned, "limit": limit})
            resp.raise_for_status()
            payload: Any = resp.json()

        return self._parse(payload, limit=limit)
