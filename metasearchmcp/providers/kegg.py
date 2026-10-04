"""Search KEGG — the Kyoto Encyclopedia of Genes and Genomes — for entries.

``kegg.jp`` is Kanehisa Laboratories' reference knowledge base that links
genes and proteins to pathways, diseases, drugs and chemical compounds.  Its
keyless REST API exposes a per-database full-text search endpoint::

    GET https://rest.kegg.jp/find/<database>/<query>

The databases searched here are ``genes`` (all organisms), ``pathway``,
``disease``, ``drug`` and ``compound``.  Every response is plain text with
one match per line formatted as ``<entry_id>\\t<description>`` — for example
``hsa:10022\\tINSL5, PRO182; insulin-like peptide INSL5 precursor``.  The
entry id is the stable KEGG identifier used to build the canonical entry page
``https://www.kegg.jp/entry/<entry_id>``.

A query is issued concurrently against each database, and the per-database
hits are merged round-robin so every database contributes to the final list.
This complements the UniProt, InterPro and Reactome providers with a source
that also covers diseases, drugs and chemical compounds.  No API key is
required.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar
from urllib.parse import quote

import httpx

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_FIND_URL = "https://rest.kegg.jp/find/"
# Canonical entry page; the entry id identifies the record.
_ENTRY_URL = "https://www.kegg.jp/entry/"
# Databases queried, in display priority order.  Earlier databases win the
# earlier round-robin slots when hits are merged.
_DATABASES: tuple[str, ...] = ("genes", "pathway", "disease", "drug", "compound")


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _parse(text: str, limit: int) -> list[tuple[str, str]]:
    """Parse a KEGG ``find`` text body into ``(entry_id, description)`` pairs.

    Lines missing a tab (and therefore a description) and duplicate entry ids
    are skipped.  At most *limit* pairs are returned.
    """
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in text.splitlines():
        entry_id, sep, description = line.partition("\t")
        entry_id = _clean(entry_id)
        description = _clean(description)
        if not sep or not entry_id or entry_id in seen:
            continue
        seen.add(entry_id)
        pairs.append((entry_id, description))
        if len(pairs) >= limit:
            break
    return pairs


class KeggProvider(BaseProvider):
    """Search genes, pathways, diseases, drugs and compounds in KEGG.

    Keyless.  Issues one request per database against the KEGG REST ``find``
    endpoint, then merges the hits round-robin so each database's best matches
    appear before a second hit from any single database.  Each result carries
    the stable entry id, the linked database and the entry's description, and
    links to the entry page on kegg.jp.  A single failing database is skipped
    rather than failing the whole search.
    """

    name = "kegg"
    description = (
        "Search KEGG — the Kyoto Encyclopedia of Genes and Genomes — across "
        "genes, pathways, diseases, drugs and compounds (stable entry id such "
        "as `hsa:10022` or `map04910`, linked database and description) via "
        "the keyless KEGG REST API, no API key required."
    )
    tags: ClassVar[list[str]] = ["academic", "web", "bio", "science"]

    def _build_result(
        self,
        entry_id: str,
        description: str,
        database: str,
        rank: int,
    ) -> SearchResult:
        """Build one :class:`SearchResult` from a parsed KEGG hit."""
        title = description or entry_id
        snippet = description or f"KEGG {database} entry {entry_id}"
        return SearchResult(
            title=title,
            url=f"{_ENTRY_URL}{quote(entry_id, safe=':')}",
            snippet=snippet[:MAX_SNIPPET_LENGTH],
            source="kegg.jp",
            rank=rank,
            provider=self.name,
            extra={
                "entry_id": entry_id,
                "database": database,
                "description": description or None,
            },
        )

    async def _search_database(
        self,
        client: httpx.AsyncClient,
        database: str,
        query: str,
        limit: int,
    ) -> list[tuple[str, str]]:
        """Search one KEGG database, returning ``[]`` on any request failure."""
        url = f"{_FIND_URL}{database}/{quote(query, safe='')}"
        try:
            resp = await client.get(url)
        except httpx.HTTPError:
            return []
        if resp.status_code != 200:
            return []
        return _parse(resp.text, limit)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search KEGG across all supported databases for *query*.

        A blank query performs no request.  Per-database hits are merged
        round-robin and ranked in the order they are emitted.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results)

        async with self._client() as client:
            per_database = await asyncio.gather(
                *(
                    self._search_database(client, database, cleaned, limit)
                    for database in _DATABASES
                ),
            )

        pools: list[tuple[str, list[tuple[str, str]]]] = [
            (database, list(pairs))
            for database, pairs in zip(_DATABASES, per_database, strict=True)
        ]

        results: list[SearchResult] = []
        seen: set[str] = set()
        while len(results) < limit:
            progressed = False
            for database, pool in pools:
                if len(results) >= limit:
                    break
                if not pool:
                    continue
                progressed = True
                entry_id, description = pool.pop(0)
                if entry_id in seen:
                    continue
                seen.add(entry_id)
                results.append(
                    self._build_result(
                        entry_id,
                        description,
                        database,
                        len(results) + 1,
                    ),
                )
            if not progressed:
                break

        return ProviderResult(results=results)
