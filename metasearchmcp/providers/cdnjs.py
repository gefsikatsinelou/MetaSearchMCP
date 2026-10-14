"""Search front-end web libraries via the keyless cdnjs API.

`cdnjs <https://cdnjs.com/>`_ hosts thousands of JavaScript and CSS
libraries and exposes a public JSON search endpoint that needs no API
key::

    GET https://api.cdnjs.com/libraries?search=chart&fields=name,description,version

Each hit carries the library ``name``, its ``latest`` built asset URL, the
current ``version``, a short ``description``, the declared ``license``, the
project ``homepage`` and a ``repository`` object.  The provider surfaces one
result per library, titled by its name and linked to the project homepage
(falling back to the cdnjs library page).  An empty ``results`` array means
no library matched the keyword and is treated as an empty result set.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_ENDPOINT = "https://api.cdnjs.com/libraries"
_SOURCE = "cdnjs"
# The search endpoint's own result cap; the provider never asks for more.
_MAX_API_RESULTS = 50
# cdnjs serves one human-readable page per library.
_LIBRARY_URL = "https://cdnjs.com/libraries/{name}"
# Only the fields the provider actually uses are requested from the API.
_FIELDS = "name,description,version,homepage,repository,license,latest"


def _clean(value: object) -> str:
    """Collapse whitespace in a string field, ignoring non-string values."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


class CdnjsProvider(BaseProvider):
    """Search front-end JavaScript and CSS libraries hosted on cdnjs.

    Keyless.  The query is a keyword matched against the library name and
    description; each match is returned with its version, license and the
    project's homepage or repository URL.
    """

    name = "cdnjs"
    description = (
        "Search thousands of front-end JavaScript and CSS libraries on cdnjs "
        "(e.g. 'chart', 'date picker' or 'carousel'). Each result carries the "
        "library name, version, license and homepage. No API key required."
    )
    tags: ClassVar[list[str]] = ["code", "developer", "web"]

    @staticmethod
    def _repository_url(repository: object) -> str:
        """Return the repository URL from a cdnjs ``repository`` object."""
        if not isinstance(repository, dict):
            return ""
        return _clean(repository.get("url"))

    def _build_result(
        self,
        item: dict[str, Any],
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a single library, or ``None``."""
        name = _clean(item.get("name"))
        if not name:
            return None

        description = _clean(item.get("description"))
        version = _clean(item.get("version"))
        license_ = _clean(item.get("license"))
        homepage = _clean(item.get("homepage"))
        repository = self._repository_url(item.get("repository"))

        snippet_parts = [description]
        if version:
            snippet_parts.append(f"v{version}")
        if license_:
            snippet_parts.append(f"License: {license_}")
        snippet = " | ".join(part for part in snippet_parts if part)

        return SearchResult(
            title=name,
            url=homepage or _LIBRARY_URL.format(name=name),
            snippet=snippet[:MAX_SNIPPET_LENGTH],
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            extra={
                "version": version or None,
                "license": license_ or None,
                "homepage": homepage or None,
                "repository": repository or None,
                "latest": _clean(item.get("latest")) or None,
            },
        )

    def _parse(self, data: object, limit: int | None = None) -> ProviderResult:
        """Parse a cdnjs search response into structured library results.

        The service's own relevance order is preserved; records without a
        usable library name are skipped and any other payload shape yields
        an empty page.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        hits = data.get("results")
        if not isinstance(hits, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in hits:
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
        """Search cdnjs for libraries matching *query*.

        A blank query performs no request.  The keyword is matched against
        the library name and description and the service's own relevance
        order is kept.
        """
        cleaned = _clean(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _ENDPOINT,
                params={
                    "search": cleaned,
                    "fields": _FIELDS,
                    "limit": limit,
                },
            )
            resp.raise_for_status()
            data: object = resp.json()

        return self._parse(data, limit)
