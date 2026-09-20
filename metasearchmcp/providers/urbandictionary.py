"""Urban Dictionary slang and idiom search via the keyless JSON API.

Urban Dictionary (urbandictionary.com) is the largest crowd-sourced dictionary
of slang, internet culture and idioms — exactly the vocabulary that mainstream
dictionaries, Wikipedia and Wiktionary rarely index.  Its public API needs no
key and serves definitions and autocomplete terms directly::

    GET https://api.urbandictionary.com/v0/define?term=<query>
    GET https://api.urbandictionary.com/v0/autocomplete?term=<query>

Every definition carries the contributing author, the up/down vote counts, an
example sentence, the submission date and a permalink to the entry.  The
autocomplete terms are surfaced as ``suggestions`` on the result envelope.

This complements the existing language providers — Wiktionary and Jisho
(dictionary entries), Datamuse (word associations) and Tatoeba (example
sentences) — with the community slang none of them cover.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote_plus

import httpx

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_DEFINE_URL = "https://api.urbandictionary.com/v0/define"
_AUTOCOMPLETE_URL = "https://api.urbandictionary.com/v0/autocomplete"
_SOURCE = "urbandictionary.com"
# The API answers a single term with a bounded set of definitions; anything
# above this is never served anyway.
_MAX_API_RESULTS = 100
# Number of autocomplete terms kept as suggestions.
_MAX_SUGGESTIONS = 8
# Longest definition / example quoted in a snippet.
_MAX_SNIPPET_DEFINITION = 220
_MAX_SNIPPET_EXAMPLE = 140
# Fallback page for entries that carry no permalink.
_TERM_URL = "https://www.urbandictionary.com/define.php?term={term}"


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _definition_text(value: object) -> str:
    """Return a definition/example with markup and stray whitespace removed.

    Urban Dictionary wraps linked headwords in square brackets (``[game]``);
    the brackets are dropped so a snippet reads as plain prose.
    """
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("[", "").replace("]", "").split())


def _int(value: object) -> int | None:
    """Return an integer field, ignoring booleans and non-integer values."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _truncate(value: str, limit: int) -> str:
    """Shorten *value* to *limit* characters, appending an ellipsis."""
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _terms(value: object) -> list[str]:
    """Return the unique autocomplete terms of an autocomplete response.

    The endpoint returns a bare JSON array of strings; a wrapped object with a
    ``terms`` field is accepted as well.
    """
    if isinstance(value, dict):
        value = value.get("terms")
    if not isinstance(value, (list, tuple)):
        return []
    terms: list[str] = []
    for entry in value:
        text = _clean(entry)
        if text and text not in terms:
            terms.append(text)
    return terms


class UrbanDictionaryProvider(BaseProvider):
    """Search Urban Dictionary for slang and idiom definitions.

    Keyless.  *query* is matched against the dictionary headwords, so a query
    returns the entries whose term matches it.  Each result carries the
    definition, an example sentence, the contributing author, the vote counts
    and the submission date of the definition.
    """

    name = "urbandictionary"
    description = (
        "Search Urban Dictionary for crowd-sourced slang and idiom definitions: "
        "definition, example usage, author, up/down votes and submission date, "
        "plus autocomplete term suggestions. No API key required."
    )
    tags: ClassVar[list[str]] = ["web", "reference", "language", "social"]

    def _snippet(self, definition: str, example: str) -> str:
        """Compose the snippet for a single definition.

        The definition comes first, followed by the example sentence so that a
        hit stays informative without reading ``extra``.  An entry without both
        fields yields an empty snippet.
        """
        parts: list[str] = []
        if definition:
            parts.append(_truncate(definition, _MAX_SNIPPET_DEFINITION))
        if example:
            parts.append(f"e.g. {_truncate(example, _MAX_SNIPPET_EXAMPLE)}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        rank: int,
        total: int | None,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from an Urban Dictionary record."""
        word = _clean(item.get("word"))
        if not word:
            return None

        definition = _definition_text(item.get("definition"))
        example = _definition_text(item.get("example"))
        written_on = _clean(item.get("written_on"))
        permalink = _clean(item.get("permalink"))

        return SearchResult(
            title=word,
            # A few legacy entries carry no permalink; fall back to the term page.
            url=permalink or _TERM_URL.format(term=quote_plus(word)),
            snippet=self._snippet(definition, example),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            published_date=self._iso_date_prefix(written_on),
            extra={
                "word": word,
                "defid": _int(item.get("defid")),
                "author": _clean(item.get("author")) or None,
                "thumbs_up": _int(item.get("thumbs_up")),
                "thumbs_down": _int(item.get("thumbs_down")),
                "written_on": written_on or None,
                "definition": definition or None,
                "example": example or None,
                "total_results": total,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse an Urban Dictionary define response into structured results.

        The API's own popularity order is preserved and duplicate definition
        ids are collapsed onto their first occurrence.  Any other payload shape
        yields an empty result set.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        entries = data.get("list")
        if not isinstance(entries, list):
            return ProviderResult(results=results)

        max_results = self._max_results if limit is None else limit
        total = len(entries)
        seen: set[int | str] = set()
        for item in entries:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            key: int | str = _int(item.get("defid")) or _clean(item.get("permalink"))
            if key and key in seen:
                continue
            built = self._build_result(item, len(results) + 1, total)
            if built is None:
                continue
            if key:
                seen.add(key)
            results.append(built)

        return ProviderResult(results=results)

    async def _suggest(self, client: httpx.AsyncClient, term: str) -> list[str]:
        """Return autocomplete terms for *term*, ignoring failures.

        Suggestions are a bonus: a failing autocomplete call must never fail
        the search itself.
        """
        try:
            resp = await client.get(_AUTOCOMPLETE_URL, params={"term": term})
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            return []
        return _terms(data)[:_MAX_SUGGESTIONS]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Urban Dictionary for definitions of *query*.

        A blank query performs no request.  The definitions are fetched in a
        single request; autocomplete suggestions are fetched alongside and are
        silently dropped when that call fails.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        if limit <= 0:
            return ProviderResult(results=[])

        async with self._client() as client:
            resp = await client.get(_DEFINE_URL, params={"term": cleaned})
            resp.raise_for_status()
            data = resp.json()
            suggestions = await self._suggest(client, cleaned)

        result = self._parse(data, limit)
        result.suggestions = suggestions
        return result
