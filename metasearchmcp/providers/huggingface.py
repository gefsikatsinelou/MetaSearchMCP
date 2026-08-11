"""Hugging Face Hub model search via the public, keyless REST API.

The Hugging Face Hub (huggingface.co) indexes millions of open AI/ML
models — LLMs, embeddings, vision, audio, and more. Its public search
endpoint requires no API key or authentication:

``GET https://huggingface.co/api/models?search=QUERY&limit=N``

Each hit includes the model id, download and like counts, pipeline task
(e.g. text-generation), and the library it is built with. Parsing uses
only the shared httpx client from the base provider.
"""

from __future__ import annotations

from typing import ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://huggingface.co/api/models"
_HUB_BASE = "https://huggingface.co"
# The Hub returns up to 1000 models per listing request; we cap client-side.
_MAX_API_RESULTS = 50
# Tag used to describe the model's primary task (e.g. "text-generation").
_TASK_TAG_PREFIX = "pipeline_tag"


class HuggingFaceProvider(BaseProvider):
    """Search AI/ML models on the Hugging Face Hub.

    Uses the keyless public REST API. Each hit carries the model id,
    download and like counts, pipeline task, and library name, with the
    URL pointing at the model's Hub page.
    """

    name = "huggingface"
    description = (
        "Search AI/ML models (LLMs, embeddings, vision, audio) on the "
        "Hugging Face Hub, no API key required."
    )
    tags: ClassVar[list[str]] = ["code", "developer", "ai", "web"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _model_url(model_id: str) -> str:
        """Return the Hub page URL for a model id."""
        if not model_id:
            return ""
        return f"{_HUB_BASE}/{model_id}"

    def _parse(self, data: object) -> ProviderResult:
        """Parse the Hub API response into structured search results."""
        results: list[SearchResult] = []
        if not isinstance(data, list):
            return ProviderResult(results=results)

        for i, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                continue
            model_id = self._clean_text(item.get("id"))
            url = self._model_url(model_id)
            if not model_id or not url:
                continue

            pipeline = self._clean_text(item.get(_TASK_TAG_PREFIX))
            library = self._clean_text(item.get("library_name"))
            downloads = int(item.get("downloads") or 0)
            likes = int(item.get("likes") or 0)

            snippet_parts: list[str] = []
            if pipeline:
                snippet_parts.append(f"Task: {pipeline}")
            if library:
                snippet_parts.append(f"Library: {library}")
            if downloads:
                snippet_parts.append(f"Downloads: {downloads:,}")
            if likes:
                snippet_parts.append(f"Likes: {likes:,}")

            results.append(
                SearchResult(
                    title=model_id,
                    url=url,
                    snippet=" | ".join(snippet_parts),
                    source="huggingface.co",
                    rank=i,
                    provider=self.name,
                    published_date=self._iso_date_prefix(item.get("lastModified")),
                    extra={
                        "pipeline_tag": pipeline,
                        "library_name": library,
                        "downloads": downloads,
                        "likes": likes,
                        "gated": bool(item.get("gated")),
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the Hugging Face Hub for models matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        payload = {"search": query, "limit": limit}
        async with self._client() as client:
            resp = await client.get(_API_URL, params=payload)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data)
