"""English dictionary lookups via the keyless dictionaryapi.dev API.

``dictionaryapi.dev`` (https://dictionaryapi.dev) is a free, keyless
wrapper around Wiktionary's English dictionary entries::

    GET https://api.dictionaryapi.dev/api/v2/entries/en/WORD

The response is a list of entries, each with the head ``word``, an
optional ``phonetic`` transcription plus a ``phonetics`` list (spelling
and audio-pronunciation URLs), and a ``meanings`` list grouped by
``partOfSpeech``.  Every meaning carries one or more ``definitions``
with the definition text, an optional usage ``example`` and per-sense
``synonyms``/``antonyms``.  A headword with no entry answers ``404``,
which is treated as "no results".

This complements the existing word providers — Wiktionary (prose),
Datamuse (word associations) and Urban Dictionary (slang) — with
structured English dictionary definitions and pronunciation.  No API
key is required.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_BASE = "https://api.dictionaryapi.dev/api/v2/entries/en"
# Human-facing reference pages for a headword: dictionaryapi.dev serves no
# per-word HTML page, and its data is sourced from Wiktionary.
_WIKTIONARY_BASE = "https://en.wiktionary.org/wiki"


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


class DictionaryApiProvider(BaseProvider):
    """Look up English dictionary definitions via the keyless dictionaryapi.dev.

    One result is produced per dictionary *definition*, so a single
    headword with several senses (e.g. a noun and a verb) yields several
    ranked hits.  Each hit carries the part of speech, the definition
    text, an optional usage example, synonyms/antonyms and, when
    available, the phonetic transcription and an audio-pronunciation URL.
    """

    name = "dictionaryapi"
    description = (
        "Look up English dictionary definitions, parts of speech, "
        "pronunciation and synonyms via the keyless dictionaryapi.dev "
        "API (Wiktionary-derived), no API key required."
    )
    tags: ClassVar[list[str]] = ["reference", "language"]

    @staticmethod
    def _phonetic(entry: dict[str, Any]) -> str:
        """Return the headword's phonetic transcription, if any."""
        direct = _clean(entry.get("phonetic"))
        if direct:
            return direct
        for item in entry.get("phonetics") or []:
            if isinstance(item, dict):
                text = _clean(item.get("text"))
                if text:
                    return text
        return ""

    @staticmethod
    def _audio(entry: dict[str, Any]) -> str:
        """Return the first pronunciation audio URL, if any."""
        for item in entry.get("phonetics") or []:
            if isinstance(item, dict):
                audio = str(item.get("audio") or "").strip()
                if audio:
                    return audio
        return ""

    @staticmethod
    def _reference_url(entry: dict[str, Any], word: str) -> str:
        """Return a human-facing reference URL for *word*.

        Prefers the entry's own ``sourceUrls`` (normally a Wiktionary
        page) and falls back to the Wiktionary URL for the headword.
        """
        sources = entry.get("sourceUrls")
        if isinstance(sources, list):
            for source in sources:
                if isinstance(source, str) and source.strip():
                    return source.strip()
        slug = quote(word.replace(" ", "_"), safe="")
        return f"{_WIKTIONARY_BASE}/{slug}"

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        """Return a list of cleaned, non-empty strings from *value*."""
        if not isinstance(value, list):
            return []
        return [cleaned for item in value if (cleaned := _clean(item))]

    def _build_result(
        self,
        *,
        word: str,
        pos: str,
        definition: dict[str, Any],
        phonetic: str,
        audio: str,
        url: str,
        rank: int,
    ) -> SearchResult:
        """Build one :class:`SearchResult` from a single dictionary sense."""
        text = _clean(definition.get("definition"))
        example = _clean(definition.get("example"))
        synonyms = self._string_list(definition.get("synonyms"))
        antonyms = self._string_list(definition.get("antonyms"))

        snippet = f"{pos}: {text}" if pos else text
        if example:
            snippet = f"{snippet} (e.g. {example})"

        extra: dict[str, Any] = {
            "part_of_speech": pos or None,
            "example": example or None,
        }
        if phonetic:
            extra["phonetic"] = phonetic
        if audio:
            extra["audio"] = audio
        if synonyms:
            extra["synonyms"] = synonyms
        if antonyms:
            extra["antonyms"] = antonyms

        return SearchResult(
            title=word,
            url=url,
            snippet=snippet[:MAX_SNIPPET_LENGTH],
            source="dictionaryapi.dev",
            rank=rank,
            provider=self.name,
            extra=extra,
        )

    def _parse(self, payload: object, limit: int) -> ProviderResult:
        """Parse a dictionaryapi.dev response into structured results.

        A non-list body (including the ``404`` "no definitions" body) means
        no results.  At most *limit* definition hits are returned.
        """
        results: list[SearchResult] = []
        if not isinstance(payload, list):
            return ProviderResult(results=results)

        for entry in payload:
            if not isinstance(entry, dict):
                continue
            word = _clean(entry.get("word"))
            if not word:
                continue
            phonetic = self._phonetic(entry)
            audio = self._audio(entry)
            url = self._reference_url(entry, word)

            for meaning in entry.get("meanings") or []:
                if not isinstance(meaning, dict):
                    continue
                pos = _clean(meaning.get("partOfSpeech"))
                for definition in meaning.get("definitions") or []:
                    if not isinstance(definition, dict):
                        continue
                    if not _clean(definition.get("definition")):
                        continue
                    if len(results) >= limit:
                        return ProviderResult(results=results)
                    results.append(
                        self._build_result(
                            word=word,
                            pos=pos,
                            definition=definition,
                            phonetic=phonetic,
                            audio=audio,
                            url=url,
                            rank=len(results) + 1,
                        ),
                    )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Look up English definitions for the headword *query*.

        A blank query performs no request.  A headword that has no entry is
        answered with ``404`` and yields an empty result set.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results)
        word = quote(cleaned.replace(" ", "_"), safe="")

        async with self._client() as client:
            resp = await client.get(f"{_API_BASE}/{word}")
            if resp.status_code == 404:
                # dictionaryapi.dev answers 404 for a headword with no entry.
                return ProviderResult(results=[])
            resp.raise_for_status()
            payload = resp.json()

        return self._parse(payload, limit)
