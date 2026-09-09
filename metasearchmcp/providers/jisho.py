"""Jisho Japanese-English dictionary search via the keyless public API.

Jisho (jisho.org) is one of the most popular Japanese-English
dictionaries.  Its read-only JSON search API requires no API key or
registration:

``GET https://jisho.org/api/v1/search/words?keyword=QUERY``

The endpoint accepts kanji, kana, romaji, and English keywords, plus
Jisho's search syntax (e.g. ``#jlpt-n3``, ``#kanji``).  Each hit is a
dictionary entry carrying the Japanese headword(s) with readings, the
English definitions grouped by part of speech, JLPT level, a common-word
flag, and WaniKani tags when available.  Data is sourced from JMDict and
JMNedict.

Jisho complements the existing Wiktionary (encyclopedic wiki entries)
and Datamuse (English word associations) providers by exposing
structured Japanese->English dictionary definitions, which is a
capability none of the current reference providers offer.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_SEARCH_URL = "https://jisho.org/api/v1/search/words"
# Jisho returns at most 20 entries per page; there is no pagination param
# on the words endpoint, so cap requests at this many.
_MAX_API_RESULTS = 20


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _strings(value: object) -> list[str]:
    """Return cleaned, non-empty strings from an API list field."""
    if not isinstance(value, list):
        return []
    return [cleaned for item in value if (cleaned := _clean(item))]


def _jlpt_label(value: object) -> str:
    """Map a Jisho JLPT tag (``jlpt-n3``) to a compact label (``N3``)."""
    cleaned = _clean(value).lower()
    prefix, sep, level = cleaned.partition("-")
    if not sep or prefix != "jlpt" or not level:
        return ""
    return "N" + level.lstrip("n").upper()


class JishoProvider(BaseProvider):
    """Search Japanese-English dictionary entries via the keyless Jisho API.

    Queries may be kanji, kana, romaji, or English words (and Jisho
    search syntax such as ``#kanji``).  Each hit carries the Japanese
    headword with readings, English definitions grouped by part of
    speech, JLPT level, and a common-word flag, so agents can answer
    "what does this word mean / how do you read this kanji" style
    lookups directly.
    """

    name = "jisho"
    description = (
        "Search Japanese-English dictionary entries via Jisho "
        "(kanji/kana/romaji/English lookup with readings, JLPT level and "
        "definitions), no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "reference", "language"]

    @staticmethod
    def _headword(entry: dict[str, Any]) -> tuple[str, list[str]]:
        """Return the display headword and readings of a Jisho entry.

        Multiple Japanese forms (e.g. kanji plus kana spelling) are
        rendered as ``word (reading)`` and joined with the Japanese
        comma ``、``; a reading without a distinct word form is shown
        on its own.  Returns an empty string when the entry carries no
        Japanese writing forms (such entries are not usable dictionary
        hits and are skipped by the parser).
        """
        forms = entry.get("japanese")
        rendered: list[str] = []
        readings: list[str] = []
        if isinstance(forms, list):
            for form in forms:
                if not isinstance(form, dict):
                    continue
                word = _clean(form.get("word"))
                reading = _clean(form.get("reading"))
                if reading and reading not in readings:
                    readings.append(reading)
                if word and reading and reading != word:
                    rendered.append(f"{word} ({reading})")
                elif word or reading:
                    rendered.append(word or reading)
        if rendered:
            return "、".join(rendered), readings
        return "", readings

    @staticmethod
    def _sense_labels(senses: object) -> list[str]:
        """Render sense glosses as ``POS: definitions`` labels."""
        labels: list[str] = []
        if not isinstance(senses, list):
            return labels
        for sense in senses[:3]:
            if not isinstance(sense, dict):
                continue
            definitions = _strings(sense.get("english_definitions"))[:3]
            if not definitions:
                continue
            pos = ", ".join(_strings(sense.get("parts_of_speech"))[:3])
            gloss = "; ".join(definitions)
            labels.append(f"{pos}: {gloss}" if pos else gloss)
        return labels

    def _parse(self, data: Any, limit: int | None = None) -> ProviderResult:
        """Parse a Jisho words search response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            return ProviderResult(results=results)
        meta = data.get("meta")
        if isinstance(meta, dict) and meta.get("status") != 200:
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for entry in data.get("data") or []:
            if len(results) >= max_results:
                break
            if not isinstance(entry, dict):
                continue

            title, readings = self._headword(entry)
            slug = _clean(entry.get("slug"))
            if not title or not slug:
                continue

            labels = self._sense_labels(entry.get("senses"))
            jlpt = [_jlpt_label(v) for v in _strings(entry.get("jlpt"))]
            jlpt = [level for level in jlpt if level]
            is_common = bool(entry.get("is_common"))

            snippet_parts = list(labels)
            if jlpt:
                snippet_parts.append("JLPT " + ", ".join(jlpt))
            if is_common:
                snippet_parts.append("Common word")
            if not snippet_parts:
                snippet_parts.append("Jisho dictionary entry")
            snippet = " | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH]

            parts_of_speech: list[str] = []
            for sense in entry.get("senses") or []:
                if isinstance(sense, dict):
                    for pos in _strings(sense.get("parts_of_speech")):
                        if pos not in parts_of_speech:
                            parts_of_speech.append(pos)
            attribution = entry.get("attribution")
            sources: list[str] = []
            if isinstance(attribution, dict):
                for dataset, included in attribution.items():
                    if isinstance(dataset, str) and included:
                        sources.append(dataset)

            results.append(
                SearchResult(
                    title=title,
                    url=f"https://jisho.org/search/{quote(slug, safe='')}",
                    snippet=snippet,
                    source="jisho.org",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "slug": slug,
                        "readings": readings,
                        "jlpt": jlpt,
                        "is_common": is_common,
                        "parts_of_speech": parts_of_speech,
                        "wanikani_tags": _strings(entry.get("tags")),
                        "sources": sources,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Jisho for dictionary entries matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        request_params = {"keyword": query}
        async with self._client() as client:
            resp = await client.get(_API_SEARCH_URL, params=request_params)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit=limit)
