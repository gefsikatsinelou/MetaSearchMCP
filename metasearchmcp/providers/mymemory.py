"""Translation across 100+ language pairs via the keyless MyMemory API.

`MyMemory <https://mymemory.translated.net>`_ is the public translation
memory operated by Translated.  Besides a large, crowd-contributed
segmented memory (``matches``) it also exposes a machine-translation
fallback, so a request always yields at least one translation when the
language pair is valid.  Its read-only JSON API is keyless::

    GET https://api.mymemory.translated.net/get?q=QUERY&langpair=SOURCE|TARGET

The response carries ``responseData`` with the primary ``translatedText``,
a ``match`` confidence and, when the source is auto-detected, a
``detectedLanguage`` code.  A ``matches`` array lists the individual
memory hits, each with ``segment``, ``translation``, ``source``/``target``
locale codes, a ``quality`` score, a ``usage-count`` and the ``match``
confidence.

The project-wide ``SearchParams.language`` is interpreted as the *target*
language (the existing two-letter tag is reused so callers need no new
option), while the source is always auto-detected.  This complements the
monolingual word providers (``dictionaryapi``, ``datamuse``,
``wiktionary``) and the example-sentence ``tatoeba`` provider with actual
phrase translation.  No API key is required.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.mymemory.translated.net/get"
# Per-translation reference page; the numeric codes are expanded by the site.
_QUERY_URL = "https://mymemory.translated.net/en"
_AUTODETECT = "Autodetect"
# Upper bound on distinct translations surfaced for a single query.
_MAX_MATCHES = 10
# Strings MyMemory returns in ``translatedText`` to signal a warning/error.
_ERROR_PREFIXES = ("MYMEMORY WARNING", "PLEASE", "NO QUERY SPECIFIED")


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field, ignoring falsey sentinels."""
    if value is None or value is False:
        return ""
    return " ".join(str(value).split())


def _as_int(value: object) -> int | None:
    """Coerce a JSON number/string to ``int``, returning ``None`` on failure."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


class MyMemoryProvider(BaseProvider):
    """Translate a phrase between languages via the keyless MyMemory API.

    Keyless.  The primary machine translation is returned first, followed
    by the distinct crowd-sourced translations from the memory (de-duplicated
    by target text and ranked by quality then usage count).  The query is
    translated into ``SearchParams.language`` (a two-letter code, default
    ``en``) with the source language auto-detected.
    """

    name = "mymemory"
    description = (
        "Translate a phrase into the target language (SearchParams.language) "
        "across 100+ language pairs via the keyless MyMemory API, returning "
        "the machine translation plus ranked crowd-sourced alternatives — "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["language", "reference", "translation"]

    @staticmethod
    def _is_error_text(text: str) -> bool:
        """Return True when *text* is a MyMemory warning/error message."""
        upper = text.upper()
        return any(upper.startswith(prefix) for prefix in _ERROR_PREFIXES)

    def _primary(
        self,
        response_data: dict[str, Any],
    ) -> tuple[str, str, object]:
        """Return the primary (machine) translation and detected language.

        Returns ``(translated_text, detected_language, match)`` where the
        translated text is empty when the payload carries no usable
        translation (e.g. a warning message).
        """
        translated = _clean(response_data.get("translatedText"))
        if translated and self._is_error_text(translated):
            return "", "", None
        detected = _clean(response_data.get("detectedLanguage"))
        return translated, detected, response_data.get("match")

    def _memory_matches(
        self,
        raw_matches: object,
        detected: str,
        primary: str,
    ) -> list[dict[str, Any]]:
        """Normalize, de-duplicate and rank the memory hits.

        Hits are de-duplicated by their (case-insensitive) translation text,
        keeping the best ``quality``/``usage-count`` seen for each.  The
        machine-translation echo of *primary* is dropped so it is not
        reported twice.
        """
        if not isinstance(raw_matches, list):
            return []

        best: dict[str, dict[str, Any]] = {}
        for item in raw_matches:
            if not isinstance(item, dict):
                continue
            translation = _clean(item.get("translation"))
            if not translation or self._is_error_text(translation):
                continue
            key = translation.lower()
            quality = _as_int(item.get("quality")) or 0
            usage = _as_int(item.get("usage-count")) or 0
            candidate = {
                "segment": _clean(item.get("segment")),
                "translation": translation,
                "source": _clean(item.get("source")) or detected,
                "target": _clean(item.get("target")),
                "quality": quality,
                "usage_count": usage,
                "match": item.get("match"),
                "reference": _clean(item.get("reference")),
            }
            current = best.get(key)
            if current is None or (quality, usage) > (
                current["quality"],
                current["usage_count"],
            ):
                best[key] = candidate

        primary_key = primary.lower()
        ranked = [
            hit for hit in best.values() if hit["translation"].lower() != primary_key
        ]
        ranked.sort(
            key=lambda hit: (-hit["quality"], -hit["usage_count"], hit["translation"]),
        )
        return ranked

    def _build_result(
        self,
        *,
        translation: str,
        segment: str,
        source_code: str,
        target: str,
        quality: int,
        usage_count: int,
        match: object,
        reference: str,
        machine: bool,
        rank: int,
    ) -> SearchResult:
        """Build one :class:`SearchResult` for a single translation."""
        snippet_parts: list[str] = []
        if segment:
            snippet_parts.append(f"{segment} -> {translation}")
        else:
            snippet_parts.append(translation)
        if quality:
            snippet_parts.append(f"quality {quality}")
        if usage_count:
            snippet_parts.append(f"used {usage_count}x")
        if machine:
            snippet_parts.append("machine translation")

        slug = quote(translation, safe="")
        url = f"{_QUERY_URL}/{source_code or 'auto'}/{target}/{slug}"
        extra: dict[str, Any] = {
            "translated_text": translation,
            "segment": segment or None,
            "source_language": source_code or None,
            "target_language": target,
            "quality": quality or None,
            "usage_count": usage_count or None,
            "match": match,
            "reference": reference or None,
            "is_machine_translation": machine,
        }
        return SearchResult(
            title=translation,
            url=url,
            snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
            source="mymemory.translated.net",
            rank=rank,
            provider=self.name,
            extra=extra,
        )

    def _parse(
        self,
        payload: object,
        limit: int,
        *,
        target: str,
    ) -> ProviderResult:
        """Parse a MyMemory ``/get`` response into structured results."""
        if not isinstance(payload, dict):
            return ProviderResult(results=[])

        # Non-200 status (int or string) signals a rejected request.
        if str(payload.get("responseStatus")) != "200":
            return ProviderResult(results=[])

        response_data = payload.get("responseData")
        if not isinstance(response_data, dict):
            return ProviderResult(results=[])

        primary, detected, primary_match = self._primary(response_data)
        source_code = (detected or "auto").lower()

        results: list[SearchResult] = []
        alternatives: list[str] = []

        if primary:
            results.append(
                self._build_result(
                    translation=primary,
                    segment="",
                    source_code=source_code,
                    target=target,
                    quality=0,
                    usage_count=0,
                    match=primary_match,
                    reference="Machine Translation.",
                    machine=True,
                    rank=1,
                ),
            )
            alternatives.append(primary)

        memory_hits = self._memory_matches(payload.get("matches"), source_code, primary)
        for hit in memory_hits:
            if len(results) >= limit:
                break
            results.append(
                self._build_result(
                    translation=hit["translation"],
                    segment=hit["segment"],
                    source_code=(hit["source"] or source_code).lower(),
                    target=target,
                    quality=hit["quality"],
                    usage_count=hit["usage_count"],
                    match=hit["match"],
                    reference=hit["reference"],
                    machine=False,
                    rank=len(results) + 1,
                ),
            )
            alternatives.append(hit["translation"])

        answer_box: dict[str, Any] | None = None
        if primary or alternatives:
            answer_box = {
                "translation": primary or (alternatives[0] if alternatives else ""),
                "source_language": source_code,
                "target_language": target,
                "alternatives": alternatives[:_MAX_MATCHES],
            }
        return ProviderResult(results=results, answer_box=answer_box)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Translate *query* into ``params.language`` via MyMemory."""
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        target = self._language_code(params.language)
        limit = min(params.num_results, self._max_results, _MAX_MATCHES)
        langpair = f"{_AUTODETECT}|{target}"

        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={"q": cleaned, "langpair": langpair},
            )
            resp.raise_for_status()
            payload = resp.json()

        return self._parse(payload, limit, target=target)
