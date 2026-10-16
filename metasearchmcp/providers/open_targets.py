"""Search the Open Targets Platform for targets, diseases and drugs.

Open Targets is a public-private partnership that integrates evidence about
the associations between therapeutic targets, diseases and drugs.  Its public
GraphQL endpoint is keyless::

    POST https://api.platform.opentargets.org/api/v4/graphql
    {"query": "...", "variables": {"queryString": "<query>"}}

The ``search`` resolver performs a free-text lookup across Open Targets
entities.  Requesting the ``target``, ``disease`` and ``drug`` entity names
returns genes/proteins, diseases (EFO/MONDO terms) and drugs (ChEMBL) in the
platform's own relevance order, each with its stable identifier, display name,
entity type and a short description.  A single request is enough; the total
number of matches is reported alongside the hits.

Each result carries the Open Targets id (e.g. ``ENSG00000139618``,
``MONDO_0007254`` or ``CHEMBL941``), the display name, the entity type, the
description and a link to the canonical record on
``platform.opentargets.org``.

A blank query performs no request and any payload without hits yields an empty
page.  No API key or registration is required.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_ENDPOINT = "https://api.platform.opentargets.org/api/v4/graphql"
_SOURCE = "platform.opentargets.org"
# Base of the Open Targets user-facing platform, used to build record links.
_PLATFORM_URL = "https://platform.opentargets.org"
# Entity groups queried together; Open Targets returns them interleaved by
# relevance.  The values map to the platform's URL path segment.
_ENTITY_NAMES = ["target", "disease", "drug"]
# Entity type -> URL path; anything unrecognized falls back to ``target``.
_ENTITY_PATHS: dict[str, str] = {
    "target": "target",
    "disease": "disease",
    "drug": "drug",
}
_DEFAULT_ENTITY = "target"
# Open Targets is happy to return large pages; the shared cap keeps payloads
# agent-friendly and mirrors the contracts result ceiling.
_MAX_API_RESULTS = 50
# Keep the description preview short so the snippet stays readable.
_DESCRIPTION_PREVIEW = 300

_QUERY = """
query Search($queryString: String!, $entityNames: [String!]!, $size: Int!) {
  search(
    queryString: $queryString
    entityNames: $entityNames
    page: {index: 0, size: $size}
  ) {
    total
    hits {
      id
      name
      entity
      description
    }
  }
}
"""


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _int(value: object) -> int | None:
    """Return *value* as an int when it is an integral number, else ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _entity_url(entity: str, entity_id: str) -> str:
    """Return the canonical Open Targets platform URL for an entity record."""
    path = _ENTITY_PATHS.get(entity, _DEFAULT_ENTITY)
    return f"{_PLATFORM_URL}/{path}/{quote(entity_id)}"


class OpenTargetsProvider(BaseProvider):
    """Search the Open Targets Platform for targets, diseases and drugs.

    Keyless.  The query is a free-text keyword matched across Open Targets
    genes/proteins, diseases and drugs; each match is returned with its stable
    identifier, entity type, description and a ``platform.opentargets.org``
    link.
    """

    name = "opentargets"
    description = (
        "Search the Open Targets Platform for drug discovery entities — "
        "therapeutic targets (genes/proteins), diseases and drugs — by "
        "keyword (e.g. 'BRCA2', 'breast cancer' or 'imatinib'). Each result "
        "carries the Open Targets id, entity type, description and a "
        "platform.opentargets.org link. No API key required."
    )
    tags: ClassVar[list[str]] = ["bio", "medical", "drugs", "academic"]

    def _build_result(
        self,
        item: dict[str, Any],
        total: int | None,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a single hit, or ``None``."""
        name = _clean(item.get("name"))
        entity_id = _clean(item.get("id"))
        if not name and not entity_id:
            return None

        entity = _clean(item.get("entity")).lower() or _DEFAULT_ENTITY
        description = _clean(item.get("description"))

        snippet_parts: list[str] = []
        if description:
            snippet_parts.append(description[:_DESCRIPTION_PREVIEW])
        snippet_parts.append(f"Type: {entity}")
        snippet = " | ".join(snippet_parts)

        return SearchResult(
            title=name or entity_id,
            url=_entity_url(entity, entity_id),
            snippet=snippet[:MAX_SNIPPET_LENGTH],
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            extra={
                "entity": entity,
                "entity_id": entity_id or None,
                "description": description or None,
                "total_matches": total,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse an Open Targets GraphQL response into structured results.

        The platform's own relevance ordering is preserved; hits without a
        usable name or identifier are skipped and any other payload shape
        yields an empty page.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        payload = data.get("data")
        if not isinstance(payload, dict):
            return ProviderResult(results=results)
        search = payload.get("search")
        if not isinstance(search, dict):
            return ProviderResult(results=results)
        hits = search.get("hits")
        if not isinstance(hits, list):
            return ProviderResult(results=results)

        total = _int(search.get("total"))

        max_results = limit or self._max_results
        for item in hits:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            built = self._build_result(item, total, len(results) + 1)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Open Targets entities for *query*.

        A blank query performs no request.  The keyword is matched against
        Open Targets targets, diseases and drugs and the platform's own
        relevance order is kept.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.post(
                _ENDPOINT,
                json={
                    "query": _QUERY,
                    "variables": {
                        "queryString": cleaned,
                        "entityNames": _ENTITY_NAMES,
                        "size": limit,
                    },
                },
            )
            resp.raise_for_status()
            data: object = resp.json()

        return self._parse(data, limit)
