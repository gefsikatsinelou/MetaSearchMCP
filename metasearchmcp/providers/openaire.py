"""OpenAIRE scholarly publication search via the public REST API.

OpenAIRE aggregates metadata for 300M+ research publications harvested from
institutional repositories, publishers, and aggregators across Europe and
worldwide (Crossref, DataCite, DOAJ, arXiv, DBLP, DSpace repositories, ...).
The search API is keyless:

``GET https://api.openaire.eu/search/publications?keywords=QUERY&format=json&size=N``

The JSON response is a lossless serialization of the underlying XML records:
field values are nested dicts/lists where the text payload lives in the
``"$"`` key and attributes use ``@``-prefixed keys.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.openaire.eu/search/publications"
_MAX_API_RESULTS = 50
_MAX_DISPLAY_AUTHORS = 3
# Precompiled pattern for stripping JATS/HTML tags from abstracts.
_TAG_RE = re.compile(r"<[^>]+>")


def _nodes(value: Any) -> list[dict[str, Any]]:
    """Normalize an XML-to-JSON serialized value into a list of dict nodes.

    OpenAIRE JSON encodes XML child elements either as a single dict or as a
    list of dicts depending on cardinality.
    """
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _text(node: Any) -> str:
    """Return the ``"$"`` text payload of an XML-to-JSON serialized node."""
    if isinstance(node, dict) and isinstance(node.get("$"), str):
        return node["$"]
    return ""


def _collapse(value: str) -> str:
    """Collapse whitespace runs and strip JATS/HTML tags from *value*."""
    value = _TAG_RE.sub(" ", value)
    return " ".join(value.split())


class OpenAIREProvider(BaseProvider):
    """Search open scholarly publications indexed by OpenAIRE.

    Uses the keyless OpenAIRE search API over the OpenAIRE Graph, which
    aggregates records for 300M+ research products (journal articles,
    preprints, book chapters) from Crossref, DataCite, DOAJ, arXiv, DBLP,
    and thousands of repositories.  Every result links to the record's DOI,
    handle, or original landing URL.
    """

    name = "openaire"
    description = (
        "Search scholarly publications indexed by OpenAIRE "
        "(300M+ open research records harvested from repositories and "
        "aggregators), no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "web"]

    @staticmethod
    def _result_url(node: dict[str, Any]) -> str:
        """Build the best landing URL for an OpenAIRE record.

        Prefers a DOI link, then a handle link, then an explicit URL pid,
        then any http(s) original identifier.  Returns ``""`` when the
        record has no resolvable identifier.
        """
        for pid in _nodes(node.get("pid")):
            kind = pid.get("@classid")
            value = _text(pid).strip()
            if not value:
                continue
            if kind == "doi":
                return f"https://doi.org/{value}"
            if kind == "handle":
                return f"https://hdl.handle.net/{value}"
            if kind == "url" and value.startswith(("http://", "https://")):
                return value
        for original in _nodes(node.get("originalId")):
            value = _text(original).strip()
            if value.startswith(("http://", "https://")):
                return value
        return ""

    @staticmethod
    def _titles(node: dict[str, Any]) -> list[str]:
        """Collect the unique main-title strings of a record, in order."""
        seen: set[str] = set()
        titles: list[str] = []
        for title_node in _nodes(node.get("title")):
            title = _text(title_node).strip()
            if title and title not in seen:
                seen.add(title)
                titles.append(title)
        return titles

    @staticmethod
    def _authors(node: dict[str, Any]) -> list[str]:
        """Extract author names from a record's creator nodes."""
        authors: list[str] = []
        for creator in _nodes(node.get("creator")):
            name = _text(creator).strip()
            if not name:
                given = str(creator.get("@name") or "").strip()
                family = str(creator.get("@surname") or "").strip()
                name = f"{given} {family}".strip()
            if name:
                authors.append(name)
        return authors

    def _parse(self, data: Any) -> ProviderResult:
        """Parse the API JSON payload into structured search results."""
        results: list[SearchResult] = []
        try:
            records = data["response"]["results"]["result"]
        except (KeyError, TypeError):
            records = []

        rank = 0
        for record in _nodes(records):
            entity = (record.get("metadata") or {}).get("oaf:entity") or {}
            node = entity.get("oaf:result")
            if not isinstance(node, dict):
                continue

            titles = self._titles(node)
            if not titles:
                continue
            url = self._result_url(node)
            if not url:
                continue

            # Duplicate main titles (varying provenance) may differ slightly,
            # e.g. a trailing period; keep the fullest variant.
            title = max(titles, key=len)

            doi = ""
            for pid in _nodes(node.get("pid")):
                if pid.get("@classid") == "doi":
                    doi = _text(pid).strip()
                    break

            description_nodes = _nodes(node.get("description"))
            abstract = ""
            if description_nodes:
                abstract = _collapse(_text(description_nodes[0]))[:MAX_SNIPPET_LENGTH]

            authors = self._authors(node)
            display_authors = authors[:_MAX_DISPLAY_AUTHORS]
            if len(authors) > _MAX_DISPLAY_AUTHORS:
                display_authors = [*display_authors, "et al."]

            container_title = _text(node.get("journal")).strip()
            header = record.get("header") or {}
            objid = _text(header.get("dri:objIdentifier")).strip()

            data_source = _text(node.get("source")).strip()
            if not data_source:
                collected = _nodes(node.get("collectedfrom"))
                if collected:
                    data_source = str(collected[0].get("@name") or "").strip()

            access_name = ""
            access_nodes = _nodes(node.get("bestaccessright"))
            if access_nodes:
                access_name = str(
                    access_nodes[0].get("@classname")
                    or access_nodes[0].get("@classid")
                    or ""
                ).strip()

            language = ""
            language_nodes = _nodes(node.get("language"))
            if language_nodes:
                language = str(
                    language_nodes[0].get("@classid") or _text(language_nodes[0])
                ).strip()

            date_prefix = _text(node.get("dateofacceptance"))[:10]
            published_date = date_prefix or None

            snippet_parts = [abstract]
            if container_title:
                snippet_parts.append(container_title)
            if display_authors:
                snippet_parts.append(", ".join(display_authors))
            if access_name:
                snippet_parts.append(f"Access: {access_name}")

            rank += 1
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" | ".join(p for p in snippet_parts if p),
                    source="openaire.eu",
                    rank=rank,
                    provider=self.name,
                    published_date=published_date,
                    extra={
                        "doi": doi,
                        "objid": objid,
                        "authors": authors,
                        "container_title": container_title,
                        "publisher": _text(node.get("publisher")).strip(),
                        "data_source": data_source,
                        "access_right": access_name,
                        "language": language,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search OpenAIRE publications for *query* and return results."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        qp = {
            "keywords": query,
            "format": "json",
            "size": str(limit),
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)
