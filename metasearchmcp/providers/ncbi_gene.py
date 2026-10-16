"""Search NCBI Gene, the NIH gene-centred information resource.

NCBI Gene is the National Center for Biotechnology Information's
gene-specific database.  It aggregates official gene nomenclature, the
map location, chromosome, aliases, the source organism and a curated
summary for genes across every sequenced organism.  Its E-utilities web
service is keyless::

    GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi
        ?db=gene&term=<query>&retmode=json&retmax=<n>
    GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi
        ?db=gene&id=<ids>&retmode=json

``esearch`` runs the free-text query — a gene symbol, a gene name, a
disease, a chromosome or an organism (or any combination) — and returns
the matching Gene IDs in the service's own relevance order.  ``esummary``
then resolves those IDs to records carrying the official symbol,
description, organism, chromosome, map location, aliases and curated
summary.

Each result links to the gene's canonical page on
``www.ncbi.nlm.nih.gov/gene``.  A blank query performs no request and a
query with no matches yields an empty page.  No API key is required for
low-volume use; setting ``NCBI_API_KEY`` raises the allowed request rate.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.config import get_settings
from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
_SOURCE = "ncbi.nlm.nih.gov"
# Base of the user-facing Gene records; each id resolves to a page here.
_GENE_URL = "https://www.ncbi.nlm.nih.gov/gene"
# NCBI caps keyless E-utilities use; keep the requested page modest and in
# step with the contracts result ceiling.
_MAX_API_RESULTS = 50
# Keep the curated summary short so the snippet stays readable.
_SUMMARY_PREVIEW = 300
# Cap the alias list so it cannot dominate the snippet.
_MAX_ALIASES = 6


def _text(value: object) -> str:
    """Return a whitespace-collapsed string for str/int values, else ``""``."""
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return " ".join(value.split())
    return ""


def _aliases(value: object) -> list[str]:
    """Split a comma-separated ``otheraliases`` string into a clean list."""
    if not isinstance(value, str):
        return []
    return [alias.strip() for alias in value.split(",") if alias.strip()]


def _organism(value: object) -> str:
    """Return the scientific (or common) name from an ``organism`` block."""
    if not isinstance(value, dict):
        return ""
    return _text(value.get("scientificname")) or _text(value.get("commonname"))


class NcbiGeneProvider(BaseProvider):
    """Search NCBI Gene for genes across all sequenced organisms.

    Keyless.  The query is free text matched by NCBI against gene symbols,
    names, diseases, chromosomes and organisms; each match is returned with
    its gene id, official symbol, description, organism, chromosome, map
    location, aliases and a ``www.ncbi.nlm.nih.gov/gene`` link.
    """

    name = "ncbi_gene"
    description = (
        "Search NCBI Gene for genes across all sequenced organisms by free "
        "text (e.g. 'BRCA2', 'tumor suppressor' or 'hemoglobin zebrafish'). "
        "Each result carries the NCBI Gene id, official symbol, description, "
        "source organism, chromosome, map location and aliases, with a "
        "www.ncbi.nlm.nih.gov/gene link. No API key required."
    )
    tags: ClassVar[list[str]] = ["bio", "medical", "academic"]

    def __init__(self) -> None:
        """Initialize the provider with the optional NCBI API key."""
        super().__init__()
        settings = get_settings()
        self._api_key: str = settings.ncbi_api_key

    def _build_result(self, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a single Gene record, or ``None``."""
        gene_id = _text(item.get("uid"))
        symbol = _text(item.get("name"))
        description = _text(item.get("description"))
        # A record without a symbol or description carries no usable label.
        if not symbol and not description:
            return None

        organism = _organism(item.get("organism"))
        chromosome = _text(item.get("chromosome"))
        map_location = _text(item.get("maplocation"))
        aliases = _aliases(item.get("otheraliases"))
        summary = _text(item.get("summary"))

        if symbol and description:
            title = f"{symbol} ({description})"
        else:
            title = symbol or description or f"NCBI Gene {gene_id}"

        snippet_parts: list[str] = []
        if organism:
            snippet_parts.append(organism)
        if chromosome:
            snippet_parts.append(f"Chromosome: {chromosome}")
        if map_location:
            snippet_parts.append(f"Location: {map_location}")
        if aliases:
            snippet_parts.append(f"Aliases: {', '.join(aliases[:_MAX_ALIASES])}")
        if summary:
            snippet_parts.append(summary[:_SUMMARY_PREVIEW])
        snippet = " | ".join(snippet_parts)

        return SearchResult(
            title=title,
            url=f"{_GENE_URL}/{gene_id}" if gene_id else _GENE_URL,
            snippet=snippet[:MAX_SNIPPET_LENGTH],
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            extra={
                "gene_id": gene_id or None,
                "symbol": symbol or None,
                "description": description or None,
                "organism": organism or None,
                "chromosome": chromosome or None,
                "map_location": map_location or None,
                "aliases": aliases,
            },
        )

    def _parse(
        self,
        data: object,
        ids: list[str],
        limit: int | None = None,
    ) -> ProviderResult:
        """Parse an ESummary response into structured results.

        The requested id order (the service's relevance order) is preserved;
        ids the summary did not return are skipped and any other payload
        shape yields an empty page.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        result_map = data.get("result")
        if not isinstance(result_map, dict):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for gene_id in ids:
            if len(results) >= max_results:
                break
            item = result_map.get(gene_id)
            if not isinstance(item, dict):
                continue
            built = self._build_result(item, len(results) + 1)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    @staticmethod
    def _id_list(payload: object) -> list[str]:
        """Extract the ordered Gene IDs from an ESearch response."""
        if not isinstance(payload, dict):
            return []
        search = payload.get("esearchresult")
        if not isinstance(search, dict):
            return []
        raw = search.get("idlist")
        if not isinstance(raw, list):
            return []
        return [
            _text(entry)
            for entry in raw
            if isinstance(entry, (str, int)) and not isinstance(entry, bool)
        ]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search NCBI Gene for *query*.

        A blank query performs no request.  ``esearch`` finds the matching
        Gene IDs and ``esummary`` resolves them, keeping the service's own
        relevance order.
        """
        cleaned = _text(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        esearch_params: dict[str, Any] = {
            "db": "gene",
            "term": cleaned,
            "retmax": limit,
            "retmode": "json",
            "sort": "relevance",
        }
        if self._api_key:
            esearch_params["api_key"] = self._api_key

        async with self._client() as client:
            resp = await client.get(_ESEARCH_URL, params=esearch_params)
            resp.raise_for_status()
            ids = self._id_list(resp.json())

            if not ids:
                return ProviderResult(results=[])

            esummary_params: dict[str, Any] = {
                "db": "gene",
                "id": ",".join(ids),
                "retmode": "json",
            }
            if self._api_key:
                esummary_params["api_key"] = self._api_key

            summary = await client.get(_ESUMMARY_URL, params=esummary_params)
            summary.raise_for_status()
            data: object = summary.json()

        return self._parse(data, ids, limit)
