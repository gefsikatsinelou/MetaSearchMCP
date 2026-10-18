"""Ansible Galaxy collection search via the public keyless Galaxy API.

`Ansible Galaxy <https://galaxy.ansible.com>`_ is the community hub and
canonical index for reusable Ansible content.  Modern content is published as
*collections* under a ``namespace.name`` identifier (with a semantic
``version``), superseding the older standalone *roles*.  The portal is backed
by Red Hat Automation Hub / Pulp and exposes a read-only search API that needs
no authentication::

    GET https://galaxy.ansible.com/api/v3/plugin/ansible/search/collection-versions/
        ?keywords=QUERY&limit=N&offset=0

The response is ``{"meta": {"count": N}, "data": [...]}``.  Each item wraps a
``collection_version`` carrying the ``namespace``, ``name``, ``version``, a
free-text ``description``, ``requires_ansible``, declared ``tags`` and a
``dependencies`` mapping, alongside ``is_highest`` / ``is_deprecated`` /
``is_signed`` flags.  Because a collection is indexed once per published
version, hits are collapsed to the highest (``is_highest``) version of each
``namespace.name`` before ranking.

This complements the existing infrastructure-as-code coverage — the Terraform
Registry provider — with the Ansible ecosystem.  No API key is required.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = (
    "https://galaxy.ansible.com/api/v3/plugin/ansible/search/collection-versions/"
)
_COLLECTION_PAGE_URL = "https://galaxy.ansible.com/ui/repo/published"

# The search API paginates its listings; keep pages small for agents.
_MAX_API_RESULTS = 100
# A single collection can appear once per version, so over-fetch the page
# before collapsing versions to still resolve enough distinct collections.
_OVERFETCH_FACTOR = 4


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


class AnsibleGalaxyProvider(BaseProvider):
    """Search Ansible Galaxy for reusable Ansible collections.

    Keyless.  Uses the ``/api/v3`` collection search endpoint and returns one
    hit per distinct ``namespace.name`` collection, preferring the highest
    published version.  Each hit carries the collection name, version,
    description, required Ansible core version, tags and declared
    dependencies.
    """

    name = "ansible_galaxy"
    description = (
        "Search Ansible Galaxy for reusable collections (namespaces, roles "
        "and modules) across the Ansible ecosystem, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "packages"]

    @staticmethod
    def _tag_names(value: object) -> list[str]:
        """Return the cleaned tag names from a collection ``tags`` list."""
        if not isinstance(value, list):
            return []
        names: list[str] = []
        for item in value:
            cleaned = _clean(item.get("name")) if isinstance(item, dict) else ""
            if cleaned:
                names.append(cleaned)
        return names

    @staticmethod
    def _dependency_names(value: object) -> list[str]:
        """Return the sorted collection names declared as dependencies."""
        if not isinstance(value, dict):
            return []
        return sorted(name for name in map(_clean, value) if name)

    def _build_result(self, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a collection search hit."""
        version_info = item.get("collection_version")
        if not isinstance(version_info, dict):
            return None

        namespace = _clean(version_info.get("namespace"))
        name = _clean(version_info.get("name"))
        if not (namespace and name):
            return None

        version = _clean(version_info.get("version"))
        description = _clean(version_info.get("description"))
        requires_ansible = _clean(version_info.get("requires_ansible"))
        tag_names = self._tag_names(version_info.get("tags"))
        dependencies = self._dependency_names(version_info.get("dependencies"))
        is_deprecated = bool(item.get("is_deprecated"))
        is_signed = bool(item.get("is_signed"))

        repository = item.get("repository")
        updated_at = ""
        if isinstance(repository, dict):
            updated_at = _clean(repository.get("pulp_last_updated"))

        identifier = f"{namespace}.{name}"
        url = f"{_COLLECTION_PAGE_URL}/{quote(namespace)}/{quote(name)}/"

        snippet_parts: list[str] = [description]
        if version:
            snippet_parts.append(f"v{version}")
        if requires_ansible:
            snippet_parts.append(f"requires Ansible {requires_ansible}")
        if tag_names:
            snippet_parts.append("tags: " + ", ".join(tag_names))
        if is_deprecated:
            snippet_parts.append("DEPRECATED")

        return SearchResult(
            title=identifier,
            url=url,
            snippet=" | ".join(p for p in snippet_parts if p)[:MAX_SNIPPET_LENGTH],
            source="galaxy.ansible.com",
            rank=rank,
            provider=self.name,
            published_date=self._iso_date_prefix(updated_at or None),
            extra={
                "namespace": namespace,
                "name": name,
                "version": version,
                "requires_ansible": requires_ansible or None,
                "tags": tag_names,
                "dependencies": dependencies,
                "dependency_count": len(dependencies),
                "is_deprecated": is_deprecated,
                "is_signed": is_signed,
            },
        )

    @staticmethod
    def _collapse(items: list[Any]) -> list[dict[str, Any]]:
        """Collapse version rows to the highest version per collection.

        The endpoint indexes a collection once per published version.  Keep
        the first-seen ordering but prefer, for each ``namespace.name``
        identifier, the row flagged ``is_highest``.
        """
        collapsed: dict[tuple[str, str], dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            version_info = item.get("collection_version")
            if not isinstance(version_info, dict):
                continue
            key = (
                _clean(version_info.get("namespace")),
                _clean(version_info.get("name")),
            )
            if not all(key):
                continue
            existing = collapsed.get(key)
            if existing is None or (
                bool(item.get("is_highest")) and not bool(existing.get("is_highest"))
            ):
                collapsed[key] = item
        return list(collapsed.values())

    def _parse(self, data: object, limit: int) -> ProviderResult:
        """Parse an Ansible Galaxy search response into structured results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        items = data.get("data")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        for item in self._collapse(items):
            if len(results) >= limit:
                break
            result = self._build_result(item, len(results) + 1)
            if result is not None:
                results.append(result)
        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Ansible Galaxy for collections matching *query*."""
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results)
        # Over-fetch so collapsing versions still leaves ``limit`` collections,
        # capped at the API page size.
        fetch_limit = min(limit * _OVERFETCH_FACTOR, _MAX_API_RESULTS)

        async with self._client() as client:
            resp = await client.get(
                _SEARCH_URL,
                params={
                    "keywords": cleaned,
                    "limit": str(fetch_limit),
                    "offset": "0",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit)
