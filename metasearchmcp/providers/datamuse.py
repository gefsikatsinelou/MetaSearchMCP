"""Datamuse word-association and thesaurus search via the keyless API.

Datamuse (datamuse.com) exposes a free, unauthenticated REST API for
word-association queries:

``GET https://api.datamuse.com/words?ml=QUERY&max=N``      (means-like)
``GET https://api.datamuse.com/words?rel_syn=QUERY&max=N`` (synonyms)
``GET https://api.datamuse.com/words?rel_ant=QUERY&max=N`` (antonyms)
``GET https://api.datamuse.com/words?sp=QUERY&max=N``      (spelled-like)

Each hit includes the word, a relevance score, and optional PoS/usage tags
(``syn``, ``n``, ``v``, ``adj``, ``prop``, ``results_type:*``). No API key
is required; parsing uses only the shared httpx client from the base
provider.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://api.datamuse.com/words"
# Datamuse caps a single request at 1000 results; keep well below that.
_MAX_API_RESULTS = 100

# Supported relation codes -> human-readable labels.
_RELATIONS: dict[str, str] = {
    "ml": "means like",
    "rel_syn": "synonym",
    "rel_ant": "antonym",
    "rel_trg": "triggers",
    "rel_jja": "often follows",
    "rel_jjb": "often precedes",
}


class DatamuseProvider(BaseProvider):
    """Search English word associations via the keyless Datamuse API.

    Queries can target a relation (means-like by default, or synonyms,
    antonyms, triggers, collocations) plus optional rhyme, spelled-like,
    or topics hints. Each hit returns the word, its relevance score, and
    usage tags (part of speech, ``syn``/``ant`` markers, results type).
    """

    name = "datamuse"
    description = (
        "Search English word associations and thesaurus terms via Datamuse "
        "(synonyms, antonyms, rhymes, related words), no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "reference", "language"]

    def _parse(self, data: Any, limit: int | None = None) -> ProviderResult:
        """Parse the Datamuse /words response into structured results."""
        results: list[SearchResult] = []
        max_results = limit or self._max_results
        if not isinstance(data, list):
            return ProviderResult(results=results)

        for i, item in enumerate(data, start=1):
            if i > max_results:
                break
            if not isinstance(item, dict):
                continue
            word = str(item.get("word") or "").strip()
            if not word:
                continue

            tags = [
                str(tag).strip() for tag in (item.get("tags") or []) if str(tag).strip()
            ]
            score = item.get("score")
            extra: dict[str, Any] = {}
            if score is not None:
                extra["score"] = int(score)
            if tags:
                extra["tags"] = tags

            snippet = ", ".join(tags)
            results.append(
                SearchResult(
                    title=word,
                    url=f"https://www.datamuse.com/words?ml={word}",
                    snippet=snippet,
                    source="datamuse.com",
                    rank=i,
                    provider=self.name,
                    extra=extra,
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Datamuse for words related to *query* and return results."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload: dict[str, str] = {"max": str(limit)}

        # Datamuse relation hints are passed as query params (e.g.
        # "ml=QUERY", "rel_syn=QUERY"); defaults to means-like when the
        # caller does not supply a relation.
        relation = (params.model_dump().get("extra") or {}).get("relation", "ml")
        code = relation if relation in _RELATIONS else "ml"
        payload[code] = query
        if code == "ml":
            for hint in ("topics", "spelled_like"):
                value = (params.model_dump().get("extra") or {}).get(hint)
                if value:
                    key = "topics" if hint == "topics" else "sp"
                    payload[key] = str(value)

        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit)
