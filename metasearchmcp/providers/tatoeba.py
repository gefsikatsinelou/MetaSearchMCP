"""Search example sentences in the Tatoeba collaborative language corpus.

Tatoeba is a free, collaboratively built collection of example sentences and
their translations, covering hundreds of languages.  Its public JSON API
supports keyword search without an API key::

    GET https://tatoeba.org/en/api_v0/search
        ?query=<query>&from=<language>&sort=relevance&page=1

``query`` is matched against the sentence text, while ``from`` restricts the
matches to a single language and expects an ISO 639-3 (three-letter) code such
as ``eng`` or ``deu``.  This provider translates the two-letter language tag
carried in ``SearchParams.language`` (``en``, ``de``, ...) into the matching
Tatoeba code so callers keep using the project-wide language option; codes
without a mapping (and therefore without a filter) fall back to searching every
language.

Each record carries the sentence text, its language (code, English name and
two-letter tag), script, licence, contributor, any alternative-script
transcription and an optional audio file.  Translations are embedded in the
response rather than returned as separate hits: the snippet lists the first few
of them and the full list is exposed in ``extra``, so an agent can inspect a
language pair without a second request.  A page holds at most ten sentences, so
the provider walks the first few pages until ``num_results`` is satisfied.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import urljoin

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_ENDPOINT = "https://tatoeba.org/en/api_v0/search"
_SOURCE = "tatoeba.org"
_SENTENCE_URL = "https://tatoeba.org/en/sentences/show/"
_AUDIO_ORIGIN = "https://tatoeba.org/"
# The API serves at most ten sentences per page.
_MAX_API_RESULTS = 10
# Upper bound on the number of pages walked to satisfy ``num_results``.
_MAX_PAGES = 5
# Number of translations quoted in a snippet.
_SNIPPET_TRANSLATIONS = 3
# Number of translation records exposed in ``extra``.
_MAX_EXPOSED_TRANSLATIONS = 5
# Longest sentence text kept verbatim as a result title.
_TITLE_MAX_LENGTH = 100

# Two-letter language tags mapped onto the ISO 639-3 codes Tatoeba expects.
_LANGUAGE_CODES: dict[str, str] = {
    "af": "afr",
    "am": "amh",
    "ar": "ara",
    "az": "aze",
    "be": "bel",
    "bg": "bul",
    "bn": "ben",
    "ca": "cat",
    "ceb": "ceb",
    "cs": "ces",
    "cy": "cym",
    "da": "dan",
    "de": "deu",
    "el": "ell",
    "en": "eng",
    "eo": "epo",
    "es": "spa",
    "et": "est",
    "eu": "eus",
    "fa": "pes",
    "fi": "fin",
    "fr": "fra",
    "ga": "gle",
    "gl": "glg",
    "he": "heb",
    "hi": "hin",
    "hr": "hrv",
    "hu": "hun",
    "hy": "hye",
    "id": "ind",
    "is": "isl",
    "it": "ita",
    "ja": "jpn",
    "jv": "jav",
    "ka": "kat",
    "kk": "kaz",
    "km": "khm",
    "ko": "kor",
    "la": "lat",
    "lt": "lit",
    "lv": "lvs",
    "mk": "mkd",
    "ml": "mal",
    "ms": "zsm",
    "mt": "mlt",
    "my": "mya",
    "nb": "nob",
    "nl": "nld",
    "nn": "nno",
    "no": "nob",
    "pl": "pol",
    "pt": "por",
    "ro": "ron",
    "ru": "rus",
    "sk": "slk",
    "sl": "slv",
    "sq": "sqi",
    "sr": "srp",
    "sv": "swe",
    "sw": "swh",
    "ta": "tam",
    "te": "tel",
    "th": "tha",
    "tl": "tgl",
    "tr": "tur",
    "uk": "ukr",
    "ur": "urd",
    "uz": "uzb",
    "vi": "vie",
    "yo": "yor",
    "yue": "yue",
    "zh": "cmn",
    "zu": "zul",
}


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _int(value: object) -> int | None:
    """Return an integer field, ignoring booleans and non-integer values."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _iso_code(language: object) -> str | None:
    """Return the Tatoeba (ISO 639-3) code matching a language tag.

    Two-letter tags are looked up in the mapping above; three-letter tags are
    passed through unchanged so callers may use ISO 639-3 directly.  Unknown
    tags yield ``None``, which leaves the API's language filter unset.
    """
    cleaned = _clean(language).lower().replace("_", "-")
    if not cleaned:
        return None
    primary = cleaned.split("-", 1)[0]
    if len(primary) == 3 and primary.isalpha():
        return primary
    return _LANGUAGE_CODES.get(primary)


def _total_results(data: dict[str, Any]) -> int | None:
    """Return the total number of matching sentences from the paging block."""
    paging = data.get("paging")
    if not isinstance(paging, dict):
        return None
    sentences = paging.get("Sentences")
    if not isinstance(sentences, dict):
        return None
    return _int(sentences.get("count"))


def _translations(value: object) -> list[dict[str, Any]]:
    """Flatten Tatoeba's grouped translation lists into plain records."""
    records: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return records
    for group in value:
        for entry in group if isinstance(group, list) else [group]:
            if not isinstance(entry, dict):
                continue
            text = _clean(entry.get("text"))
            if not text:
                continue
            records.append(
                {
                    "id": _int(entry.get("id")),
                    "language": _clean(entry.get("lang")) or None,
                    "language_name": _clean(entry.get("lang_name")) or None,
                    "text": text,
                }
            )
    return records


def _transcription(value: object) -> str:
    """Return the first alternative-script transcription of a sentence."""
    if not isinstance(value, list):
        return ""
    for entry in value:
        if isinstance(entry, dict):
            text = _clean(entry.get("text"))
            if text:
                return text
    return ""


def _audio_url(value: object) -> str:
    """Return the absolute download URL of a sentence's first audio file."""
    if not isinstance(value, list):
        return ""
    for entry in value:
        if not isinstance(entry, dict):
            continue
        path = _clean(entry.get("download_url"))
        if path:
            return urljoin(_AUDIO_ORIGIN, path)
    return ""


class TatoebaProvider(BaseProvider):
    """Search Tatoeba example sentences and their translations.

    Keyless.  *query* is matched against sentence text, optionally narrowed to
    the language given in ``SearchParams.language``; every hit links to its
    sentence page and lists the translations, licence and contributor.
    """

    name = "tatoeba"
    description = (
        "Search Tatoeba, a collaborative corpus of example sentences with "
        "translations in hundreds of languages: sentence text, language, "
        "contributor, licence, alternative-script transcription, audio and "
        "translations into other languages. No API key required."
    )
    tags: ClassVar[list[str]] = ["web", "reference", "language"]

    def _title(self, text: str) -> str:
        """Truncate a sentence so it fits comfortably in a result title."""
        if len(text) <= _TITLE_MAX_LENGTH:
            return text
        return text[: _TITLE_MAX_LENGTH - 3].rstrip() + "..."

    def _snippet(self, item: dict[str, Any], translations: list[dict[str, Any]]) -> str:
        """Compose the snippet for a sentence record.

        The language, any alternative-script transcription, the first few
        translations, the contributor and the presence of audio are combined so
        that a result stays informative without reading ``extra``.
        """
        parts: list[str] = []

        language = _clean(item.get("lang_name")) or _clean(item.get("lang"))
        if language:
            parts.append(language)

        transcription = _transcription(item.get("transcriptions"))
        if transcription:
            parts.append(transcription)

        for translation in translations[:_SNIPPET_TRANSLATIONS]:
            name = translation["language_name"] or translation["language"] or ""
            text = translation["text"]
            parts.append(f"{text} ({name})" if name else text)

        user = item.get("user")
        owner = _clean(user.get("username")) if isinstance(user, dict) else ""
        if owner:
            parts.append(f"by {owner}")

        if _audio_url(item.get("audios")):
            parts.append("audio available")

        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        total: int | None,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a Tatoeba sentence record."""
        sentence_id = _int(item.get("id"))
        text = _clean(item.get("text"))
        if sentence_id is None or not text:
            return None

        translations = _translations(item.get("translations"))
        user = item.get("user")
        owner = _clean(user.get("username")) if isinstance(user, dict) else ""
        url = f"{_SENTENCE_URL}{sentence_id}"

        return SearchResult(
            title=self._title(text),
            url=url,
            snippet=self._snippet(item, translations),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            extra={
                "sentence_id": sentence_id,
                "language": _clean(item.get("lang")) or None,
                "language_name": _clean(item.get("lang_name")) or None,
                "language_tag": _clean(item.get("lang_tag")) or None,
                "script": _clean(item.get("script")) or None,
                "license": _clean(item.get("license")) or None,
                "owner": owner or None,
                "transcription": _transcription(item.get("transcriptions")) or None,
                "audio_url": _audio_url(item.get("audios")) or None,
                "sentence_url": url,
                "translations": translations[:_MAX_EXPOSED_TRANSLATIONS],
                "translation_count": len(translations),
                "total_results": total,
            },
        )

    def _parse(
        self,
        data: object,
        limit: int | None = None,
        start_rank: int = 1,
    ) -> ProviderResult:
        """Parse one page of a Tatoeba response into structured results.

        Tatoeba's own relevance order is preserved; any other payload shape
        yields an empty page.  *start_rank* numbers the page's hits so that
        paging through several pages keeps a continuous ranking.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        items = data.get("results")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        total = _total_results(data)
        max_results = self._max_results if limit is None else limit
        for item in items:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            built = self._build_result(item, total, start_rank + len(results))
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    @staticmethod
    def _request_params(query: str, language: str, page: int) -> dict[str, Any]:
        """Build the query string for one page of Tatoeba results."""
        request: dict[str, Any] = {
            "query": query,
            "sort": "relevance",
            "page": page,
        }
        code = _iso_code(language)
        if code:
            request["from"] = code
        return request

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Tatoeba sentences for *query*.

        A blank query performs no request.  The language in ``params.language``
        narrows the search to that language when a Tatoeba code is known;
        otherwise every language is searched.  Pages of ten sentences are
        fetched until ``num_results`` is reached, at most ``_MAX_PAGES`` times.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results)
        if limit <= 0:
            return ProviderResult(results=[])

        results: list[SearchResult] = []
        async with self._client() as client:
            for page in range(1, _MAX_PAGES + 1):
                resp = await client.get(
                    _ENDPOINT,
                    params=self._request_params(cleaned, params.language, page),
                )
                resp.raise_for_status()
                page_result = self._parse(
                    resp.json(),
                    limit - len(results),
                    start_rank=len(results) + 1,
                )
                results.extend(page_result.results)
                if len(results) >= limit or len(page_result.results) < _MAX_API_RESULTS:
                    break

        return ProviderResult(results=results)
