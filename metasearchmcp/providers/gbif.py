"""GBIF species search via the keyless public API.

GBIF (gbif.org) is the Global Biodiversity Information Facility, an
international network aggregating biodiversity data from thousands of
publisher datasets. Its public species search endpoint requires no API key:

``GET https://api.gbif.org/v1/species/search?q=QUERY&limit=N``

Each hit is a taxon record carrying the scientific and canonical names,
taxonomic rank, status (accepted/synonym), the higher classification
(kingdom, phylum, class, order, family, genus), threat status, and any
common (vernacular) names. The provider is keyless, uses only the shared
httpx client, and tags itself ``biodiversity``/``nature``/``science`` so
it complements the existing iNaturalist provider in nature searches.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.gbif.org/v1/species/search"
# GBIF caps a single request at 300 results; keep well below that.
_MAX_API_RESULTS = 50

# Classification ranks that may appear in a taxon record.
_RANK_KEYS = ("kingdom", "phylum", "class", "order", "family", "genus")


class GBIFSpeciesProvider(BaseProvider):
    """Search taxon records in the GBIF species backbone.

    Keyless. Uses the public ``/v1/species/search`` endpoint (``?q=QUERY``)
    to find matching taxa. Each hit carries the scientific name, canonical
    name, rank, taxonomic status, higher classification, threat status, and
    common names.
    """

    name = "gbif"
    description = (
        "Search species and taxon records in the GBIF biodiversity "
        "backbone — scientific names, classification, and conservation "
        "status via the keyless public API."
    )
    tags: ClassVar[list[str]] = ["biodiversity", "nature", "science"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _classification(item: dict[str, Any]) -> str:
        """Compose a compact higher-classification chain like ``Mammalia > Felidae``."""
        ranks = [GBIFSpeciesProvider._clean(item.get(key)) for key in _RANK_KEYS]
        chain = [rank for rank in ranks if rank]
        return " > ".join(chain) if chain else ""

    def _parse(self, data: Any, limit: int | None = None) -> ProviderResult:
        """Parse the /v1/species/search response into structured results.

        The response is an object with a ``results`` list; each element is
        one taxon record. Non-dict entries and records without a scientific
        name are skipped.
        """
        results: list[SearchResult] = []
        max_results = limit or self._max_results
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        records = data.get("results")
        if not isinstance(records, list):
            return ProviderResult(results=results)

        for item in records:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue

            scientific = self._clean(item.get("scientificName"))
            if not scientific:
                continue

            canonical = self._clean(item.get("canonicalName"))
            title = canonical or scientific
            rank = self._clean(item.get("rank"))
            status = self._clean(item.get("taxonomicStatus"))
            classification = self._classification(item)
            threat = (
                self._clean(item.get("threatStatuses")[0])
                if item.get("threatStatuses")
                else ""
            )
            common_names = [
                self._clean(name.get("vernacularName"))
                for name in (item.get("vernacularNames") or [])
                if isinstance(name, dict)
            ]
            common_names = [name for name in common_names if name]

            snippet_parts: list[str] = []
            if scientific and scientific != title:
                snippet_parts.append(scientific)
            if rank:
                snippet_parts.append(rank)
            if status:
                snippet_parts.append(status)
            if classification:
                snippet_parts.append(classification)
            if threat:
                snippet_parts.append(f"Conservation: {threat}")
            if common_names:
                snippet_parts.append(f"Common: {', '.join(common_names[:3])}")

            taxon_key = item.get("key")
            results.append(
                SearchResult(
                    title=title,
                    url=(
                        f"https://www.gbif.org/species/{taxon_key}"
                        if taxon_key
                        else "https://www.gbif.org/"
                    ),
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source="gbif.org",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "scientific_name": scientific,
                        "canonical_name": canonical,
                        "rank": rank,
                        "taxonomic_status": status,
                        "classification": classification,
                        "threat_status": threat,
                        "common_names": common_names,
                        "synonym": bool(item.get("synonym")),
                        "num_occurrences": item.get("numOccurrences"),
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search GBIF for taxon records matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(_API_URL, params={"q": query, "limit": limit})
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit)
