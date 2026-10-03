"""Search Reactome — a curated database of biological pathways — for entities.

``reactome.org`` is an open, manually curated knowledgebase of biological
pathways, reactions, proteins and small molecules spanning ~20 species.  Its
public Content Service exposes a keyless full-text search endpoint::

    GET https://reactome.org/ContentService/search/query?query=QUERY&cluster=true

The response is ``{"results": [{"typeName": ..., "entries": [...]}, ...],
"rowCount": N, "numberOfGroups": G, "numberOfMatches": M}``.  Each entry
carries a stable Reactome identifier (``stId`` such as ``R-HSA-70171``), a
display ``name``, an entity ``type``/``exactType``, the ``species`` it belongs
to, optional ``compartmentNames`` and — for pathways — a ``summation`` summary.

Matched terms in ``name`` and ``summation`` are wrapped in
``<span class="highlighting">`` markup, which is stripped before use.  This
complements the other biomedical providers with an explicit pathway and
reaction catalogue.  No API key is required.
"""

from __future__ import annotations

import html
import re
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://reactome.org/ContentService/search/query"
# Canonical detail page for a stable Reactome identifier.
_DETAIL_URL = "https://reactome.org/content/detail/"
# Reactome clusters hits by entity type; cap how many entries we keep.
_MAX_API_RESULTS = 100
# Characters of the pathway summary copied into the snippet.
_SNIPPET_SUMMARY_LENGTH = 240
# Species and compartment values listed in the snippet.
_SNIPPET_LIST_LIMIT = 3

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(value: object) -> str:
    """Strip HTML markup, collapse whitespace and unescape entities."""
    if not value:
        return ""
    text = _TAG_RE.sub(" ", str(value))
    return " ".join(html.unescape(text).split())


def _string_list(value: object, limit: int) -> list[str]:
    """Return a deduplicated list of up to *limit* clean strings from *value*."""
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for entry in value:
        label = _clean(entry)
        if label and label not in items:
            items.append(label)
        if len(items) >= limit:
            break
    return items


class ReactomeProvider(BaseProvider):
    """Search biological pathways, reactions and molecules in Reactome.

    Keyless.  Issues a single request against the Reactome Content Service
    full-text search endpoint and returns one hit per matched entity, carrying
    the stable identifier, entity type, species and — for pathways — a summary,
    linking to the record page on reactome.org.
    """

    name = "reactome"
    description = (
        "Search Reactome — a curated database of biological pathways — for "
        "pathways, reactions, proteins and small molecules (stable identifier, "
        "entity type, species, compartment and pathway summary) via the "
        "keyless Reactome Content Service, no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "web", "bio", "science"]

    @staticmethod
    def _snippet(
        summary: str,
        entity_type: str,
        species: list[str],
        compartments: list[str],
    ) -> str:
        """Compose the snippet for a single Reactome entity."""
        parts: list[str] = []
        if summary:
            parts.append(summary[:_SNIPPET_SUMMARY_LENGTH])
        if entity_type:
            parts.append(f"Type: {entity_type}")
        if species:
            parts.append(f"Species: {', '.join(species[:_SNIPPET_LIST_LIMIT])}")
        if compartments:
            parts.append(
                f"Compartment: {', '.join(compartments[:_SNIPPET_LIST_LIMIT])}"
            )
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(self, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw Reactome entry."""
        stable_id = _clean(item.get("stId"))
        title = _clean(item.get("name"))
        if not stable_id or not title:
            return None

        entity_type = _clean(item.get("type")) or _clean(item.get("exactType"))
        species = _string_list(item.get("species"), _SNIPPET_LIST_LIMIT)
        compartments = _string_list(
            item.get("compartmentNames"),
            _SNIPPET_LIST_LIMIT,
        )
        summary = _clean(item.get("summation"))

        return SearchResult(
            title=title,
            url=f"{_DETAIL_URL}{stable_id}",
            snippet=self._snippet(summary, entity_type, species, compartments),
            source="reactome.org",
            rank=rank,
            provider=self.name,
            extra={
                "id": stable_id,
                "db_id": item.get("dbId"),
                "type": entity_type or None,
                "exact_type": _clean(item.get("exactType")) or None,
                "species": species,
                "compartments": compartments,
                "reference_name": _clean(item.get("referenceName")) or None,
                "reference_identifier": _clean(item.get("referenceIdentifier")) or None,
                "database": _clean(item.get("databaseName")) or None,
                "reference_url": _clean(item.get("referenceURL")) or None,
                "is_disease": bool(item.get("isDisease")),
            },
        )

    def _parse(self, data: object, limit: int) -> list[SearchResult]:
        """Parse a Reactome search response, deduplicating by stable id."""
        if not isinstance(data, dict):
            return []
        groups = data.get("results")
        if not isinstance(groups, list):
            return []

        results: list[SearchResult] = []
        seen: set[str] = set()
        for group in groups:
            if not isinstance(group, dict):
                continue
            entries = group.get("entries")
            if not isinstance(entries, list):
                continue
            for item in entries:
                if len(results) >= limit:
                    return results
                if not isinstance(item, dict):
                    continue
                stable_id = _clean(item.get("stId"))
                if not stable_id or stable_id in seen:
                    continue
                seen.add(stable_id)
                built = self._build_result(item, len(results) + 1)
                if built is None:
                    continue
                results.append(built)
        return results

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Reactome for entities matching *query*.

        A blank query performs no request.  Reactome ranks matches by its own
        relevance score, which is preserved in the returned order.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={"query": cleaned, "cluster": "true"},
            )
            resp.raise_for_status()
            data = resp.json()

        return ProviderResult(results=self._parse(data, limit))
