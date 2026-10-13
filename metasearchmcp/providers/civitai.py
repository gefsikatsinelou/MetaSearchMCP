"""Search AI image-generation models on Civitai.

Civitai is a community repository of generative-AI image models — Stable
Diffusion checkpoints, LoRAs, textual inversions, control nets and similar.
Its public API supports keyword search without an API key::

    GET https://civitai.com/api/v1/models
        ?query=<query>&limit=10&sort=Most Downloaded&nsfw=false

The keyword is matched against model names, descriptions, tags and creator
names, and Civitai's own relevance/download ranking is preserved.  A single
request returns up to ``limit`` (max 100) models plus a ``metadata`` block
carrying the cursor for the next page, so — like the Flickr and Wallhaven
providers — results are paginated by the caller rather than by this provider.

Each record carries the model id, name, ``type`` (``Checkpoint``, ``LORA``,
``TextualInversion``, ...), tags, creator, aggregated download/like/comment
counts and the newest published version (its name, base model, trained words
and download URL).  Because many entries are adult-only, ``safe_search`` maps
onto the API's ``nsfw`` toggle: a safe search asks for safe-for-work models
only, while an unrestricted search also allows adult entries.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_ENDPOINT = "https://civitai.com/api/v1/models"
_SOURCE = "civitai.com"
# Canonical model page, keyed by its Civitai id.
_MODEL_URL = "https://civitai.com/models/{model_id}"
# Civitai caps ``limit`` at 100 models for a single request.
_MAX_API_RESULTS = 100
# Number of tags listed in a snippet.
_MAX_SNIPPET_TAGS = 5


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


def _strings(value: object) -> list[str]:
    """Return the non-empty string entries of a list-valued field."""
    if not isinstance(value, (list, tuple)):
        return []
    return [text for entry in value if (text := _clean(entry))]


def _username(value: object) -> str:
    """Return the creator's username from a Civitai ``creator`` object."""
    if not isinstance(value, dict):
        return ""
    return _clean(value.get("username"))


def _latest_version(item: dict[str, Any]) -> dict[str, Any]:
    """Return the newest model version, or an empty mapping when absent."""
    versions = item.get("modelVersions")
    if not isinstance(versions, list):
        return {}
    for version in versions:
        if isinstance(version, dict):
            return version
    return {}


def _base_model(item: dict[str, Any], version: dict[str, Any]) -> str:
    """Return the version's base model, falling back to the model's list."""
    base = _clean(version.get("baseModel"))
    if base:
        return base
    models = _strings(item.get("baseModels"))
    return models[0] if models else ""


def _preview_image(version: dict[str, Any]) -> str:
    """Return the first preview image URL attached to a model version."""
    images = version.get("images")
    if not isinstance(images, list):
        return ""
    for image in images:
        if isinstance(image, dict):
            url = _clean(image.get("url"))
            if url:
                return url
    return ""


def _label(value: object) -> str:
    """Render a Civitai enum field (``Checkpoint``, ``LORA``) for display."""
    return _clean(value)


class CivitaiProvider(BaseProvider):
    """Search AI image-generation models in the Civitai repository.

    Keyless.  A single request matches *query* against Civitai's model
    metadata and returns hits in Civitai's own ranking, each carrying its
    type, tags, creator, download/like/comment counts and newest version
    details (base model, trained words, download URL and preview image).
    """

    name = "civitai"
    description = (
        "Search Civitai, the community repository of generative-AI image "
        "models: Stable Diffusion checkpoints, LoRAs and more by keyword. "
        "Each result carries the model type, tags, creator, download/like "
        "counts and the newest version's base model, trained words, download "
        "URL and preview image. No API key required."
    )
    tags: ClassVar[list[str]] = ["image", "media", "ai"]

    def _title(self, item: dict[str, Any], model_id: str) -> str:
        """Return a model's name, falling back to its identifier."""
        return _clean(item.get("name")) or f"Civitai model {model_id}"

    def _snippet(self, item: dict[str, Any], version: dict[str, Any]) -> str:
        """Compose the snippet for a single model record.

        Type, base model, download/like counts, tags and creator are combined
        so that a result stays informative even when the caller does not look
        at ``extra``.
        """
        parts: list[str] = []

        model_type = _label(item.get("type"))
        if model_type:
            parts.append(model_type)

        base_model = _base_model(item, version)
        if base_model:
            parts.append(base_model)

        stats = item.get("stats")
        stats = stats if isinstance(stats, dict) else {}
        downloads = _int(stats.get("downloadCount"))
        if downloads is not None:
            parts.append(f"{downloads:,} downloads")

        thumbs_up = _int(stats.get("thumbsUpCount"))
        if thumbs_up is not None:
            parts.append(f"{thumbs_up:,} likes")

        tags = _strings(item.get("tags"))[:_MAX_SNIPPET_TAGS]
        if tags:
            parts.append(" ".join(tags))

        creator = _username(item.get("creator"))
        if creator:
            parts.append(f"by {creator}")

        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a Civitai model record."""
        model_id = _int(item.get("id"))
        if model_id is None:
            return None

        version = _latest_version(item)
        stats = item.get("stats")
        stats = stats if isinstance(stats, dict) else {}
        version_stats = version.get("stats")
        version_stats = version_stats if isinstance(version_stats, dict) else {}

        return SearchResult(
            title=self._title(item, str(model_id)),
            url=_MODEL_URL.format(model_id=model_id),
            snippet=self._snippet(item, version),
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            published_date=self._iso_date_prefix(_clean(version.get("publishedAt"))),
            extra={
                "civitai_id": model_id,
                "type": _label(item.get("type")) or None,
                "nsfw": item.get("nsfw") is True,
                "creator": _username(item.get("creator")) or None,
                "tags": _strings(item.get("tags")),
                "download_count": _int(stats.get("downloadCount")),
                "thumbs_up": _int(stats.get("thumbsUpCount")),
                "thumbs_down": _int(stats.get("thumbsDownCount")),
                "comment_count": _int(stats.get("commentCount")),
                "base_model": _base_model(item, version) or None,
                "latest_version": _clean(version.get("name")) or None,
                "version_id": _int(version.get("id")),
                "trained_words": _strings(version.get("trainedWords")),
                "version_download_count": _int(version_stats.get("downloadCount")),
                "download_url": _clean(version.get("downloadUrl")) or None,
                "preview_image": _preview_image(version) or None,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a Civitai search response into structured results.

        Civitai's own ranking order is preserved; any other payload shape
        yields an empty page.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        items = data.get("items")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in items:
            if len(results) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            built = self._build_result(item, len(results) + 1)
            if built is None:
                continue
            results.append(built)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Civitai models for *query*.

        A blank query performs no request.  Civitai matches the keyword
        against model metadata and returns hits in its own ranking.  When
        ``params.safe_search`` is set only safe-for-work models are requested;
        otherwise adult entries are allowed as well.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        request_params: dict[str, Any] = {
            "query": cleaned,
            "limit": limit,
            "sort": "Most Downloaded",
            "nsfw": "true" if not params.safe_search else "false",
        }
        async with self._client() as client:
            resp = await client.get(_ENDPOINT, params=request_params)
            resp.raise_for_status()
            data: object = resp.json()

        return self._parse(data, limit)
