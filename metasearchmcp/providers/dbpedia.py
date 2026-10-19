"""Entity search via the keyless DBpedia Lookup API.

`DBpedia <https://www.dbpedia.org/>`_ extracts structured data from Wikipedia
into a Linked Data knowledge graph.  Its public *Lookup* service resolves a
free-text query to matching entities and needs no API key::

    GET https://lookup.dbpedia.org/api/search?query=QUERY&format=JSON

The response is a JSON object whose ``docs`` array holds the matching entities.
Each entry carries the entity ``label``, a short ``comment`` (abstract), the
canonical DBpedia ``resource``/``id`` IRI, the ontology ``type``/``typeName``
classes, relative ``refCount`` (inbound-link popularity) and the Wikipedia
``category`` memberships.  Labels and comments include ``<B>`` highlight markup
and HTML entities, which are stripped before they are returned.  No API key is
required.
"""

from __future__ import annotations

import html
import re
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_LOOKUP_URL = "https://lookup.dbpedia.org/api/search"
_DBPEDIA_ONTOLOGY = "http://dbpedia.org/ontology/"
_DBPEDIA_CATEGORY = "http://dbpedia.org/resource/Category:"
# Upper bound on entities surfaced for a single query.
_MAX_RESULTS = 25
# Maximum entity categories kept in the parsed ``extra`` payload.
_MAX_CATEGORIES = 8

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(value: object) -> str:
    """Strip highlight markup/HTML entities and collapse whitespace."""
    if value is None:
        return ""
    text = html.unescape(_TAG_RE.sub("", str(value)))
    return " ".join(text.split())


def _first(doc: dict[str, Any], key: str) -> str:
    """Return the first string value of *key*, tolerating str or list values."""
    value = doc.get(key)
    if isinstance(value, list):
        value = value[0] if value else None
    return _clean(value)


def _as_list(doc: dict[str, Any], key: str) -> list[str]:
    """Return *key*'s values as a list of cleaned strings."""
    value = doc.get(key)
    if isinstance(value, list):
        return [clean for item in value if (clean := _clean(item))]
    if value is None:
        return []
    cleaned = _clean(value)
    return [cleaned] if cleaned else []


class DBpediaProvider(BaseProvider):
    """Search entities in the DBpedia knowledge graph.

    Keyless.  Uses the DBpedia Lookup API to resolve a query to linked-data
    entities, returning each entity's label, abstract, ontology types,
    popularity and category memberships, linking to its DBpedia resource page.
    """

    name = "dbpedia"
    description = (
        "Search the DBpedia knowledge graph for entities extracted from "
        "Wikipedia. Returns each entity's label, abstract, ontology types, "
        "reference count and category memberships, linking to its DBpedia "
        "resource page; no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "academic", "knowledge", "reference"]

    def _ontology_types(self, doc: dict[str, Any]) -> list[str]:
        """Return concise type names from the ``type``/``typeName`` fields."""
        names = _as_list(doc, "typeName")
        if not names:
            names = [
                uri.rsplit("/", 1)[-1]
                for uri in _as_list(doc, "type")
                if uri.startswith(_DBPEDIA_ONTOLOGY)
            ]
        # De-duplicate while preserving order.
        return list(dict.fromkeys(names))

    def _categories(
        self, doc: dict[str, Any], limit: int = _MAX_CATEGORIES
    ) -> list[str]:
        """Return readable Wikipedia category names for an entity."""
        names = [
            uri.split("Category:", 1)[1].replace("_", " ")
            for uri in _as_list(doc, "category")
            if uri.startswith(_DBPEDIA_CATEGORY)
        ]
        return list(dict.fromkeys(names))[:limit]

    def _entity_result(self, doc: object, rank: int) -> SearchResult | None:
        """Build one result from a single DBpedia Lookup document."""
        if not isinstance(doc, dict):
            return None

        resource = doc.get("resource") or doc.get("id")
        resource_url = ""
        if isinstance(resource, list):
            resource = resource[0] if resource else None
        if resource is not None:
            resource_url = _clean(resource)
        # Fall back to the ``id`` field when ``resource`` is absent.
        if not resource_url:
            resource_url = _first(doc, "id")

        title = _first(doc, "label")
        if not title and resource_url:
            title = resource_url.rsplit("/", 1)[-1].replace("_", " ")
        if not title:
            return None

        url = resource_url or f"https://dbpedia.org/page/{title.replace(' ', '_')}"
        comment = _first(doc, "comment")
        types = self._ontology_types(doc)
        categories = self._categories(doc)

        snippet_parts: list[str] = []
        if comment:
            snippet_parts.append(comment)
        if types:
            snippet_parts.append("types: " + ", ".join(types))

        return SearchResult(
            title=title,
            url=url,
            snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
            source="dbpedia.org",
            provider=self.name,
            rank=rank,
            extra={
                "resource": resource_url,
                "abstract": comment,
                "types": types,
                "categories": categories,
                "ref_count": _first(doc, "refCount"),
                "score": _first(doc, "score"),
            },
        )

    def _parse(self, payload: object, limit: int | None = None) -> ProviderResult:
        """Parse a DBpedia Lookup response into structured results."""
        if not isinstance(payload, dict):
            return ProviderResult(results=[])
        docs = payload.get("docs")
        if not isinstance(docs, list):
            return ProviderResult(results=[])

        max_results = limit or self._max_results
        results: list[SearchResult] = []
        for doc in docs:
            if len(results) >= max_results:
                break
            result = self._entity_result(doc, rank=len(results) + 1)
            if result is None:
                continue
            results.append(result)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search DBpedia for entities matching *query*."""
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _LOOKUP_URL,
                params={"query": cleaned, "format": "JSON", "maxResults": limit},
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            payload: Any = resp.json()

        return self._parse(payload, limit=limit)
