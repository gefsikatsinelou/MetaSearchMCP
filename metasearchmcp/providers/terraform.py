"""Terraform Registry module and provider search via the public keyless API.

The Terraform Registry (registry.terraform.io) is the canonical index for
reusable Terraform *modules* and *providers* across every major cloud and SaaS
target (AWS, Azure, Google Cloud, Kubernetes, Helm, Datadog, Cloudflare, ...).
It exposes a read-only search API that needs no authentication::

    GET https://registry.terraform.io/v1/modules?q=QUERY&limit=N&offset=0
    GET https://registry.terraform.io/v1/providers?q=QUERY&limit=N&offset=0

Both endpoints return JSON.  A module hit carries the ``namespace/name`` pair,
the targeted ``provider`` (``aws``, ``google``, ...), the latest version,
description, download count, upstream source repository and publication
timestamp; a provider hit carries the same minus the target, plus a support
``tier`` (``official``, ``partner``, ``community``).

This complements the existing package-registry providers (npm, PyPI, NuGet,
Maven, Chocolatey, ...) with the infrastructure-as-code ecosystem, which none
of them cover.  No API key is required.
"""

from __future__ import annotations

import asyncio
from itertools import zip_longest
from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_MODULES_URL = "https://registry.terraform.io/v1/modules"
_PROVIDERS_URL = "https://registry.terraform.io/v1/providers"
_MODULE_PAGE_URL = "https://registry.terraform.io/modules/"
_PROVIDER_PAGE_URL = "https://registry.terraform.io/providers/"

# The registry paginates its listings; keep pages small for agents.
_MAX_API_RESULTS = 25


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


class TerraformRegistryProvider(BaseProvider):
    """Search the Terraform Registry for modules and providers.

    Keyless.  Queries the module and provider search endpoints concurrently and
    interleaves the two result sets so neither kind crowds out the other.  Each
    hit carries the namespace/name (plus the target provider for modules), the
    latest version, description, download count and upstream source repository.
    """

    name = "terraform"
    description = (
        "Search the Terraform Registry for reusable modules and providers "
        "(AWS, Azure, Google Cloud, Kubernetes, ...), no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "code", "developer", "packages"]

    @staticmethod
    def _downloads(value: object) -> int:
        """Return *value* as a download count, ignoring non-integers."""
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return 0

    @staticmethod
    def _snippet(
        description: str,
        version: str,
        downloads: int,
        label: str,
    ) -> str:
        """Compose the snippet for a single registry entry."""
        parts: list[str] = []
        if description:
            parts.append(description)
        if version:
            parts.append(f"v{version}")
        if downloads:
            parts.append(f"Downloads: {downloads:,}")
        if label:
            parts.append(label)
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _module_result(self, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a module search hit."""
        namespace = _clean(item.get("namespace"))
        name = _clean(item.get("name"))
        target = _clean(item.get("provider"))
        if not (namespace and name and target):
            return None

        version = _clean(item.get("version"))
        downloads = self._downloads(item.get("downloads"))
        verified = bool(item.get("verified"))
        url = f"{_MODULE_PAGE_URL}{quote(namespace)}/{quote(name)}/{quote(target)}"
        if version:
            url = f"{url}/{quote(version)}"

        return SearchResult(
            title=f"{namespace}/{name}/{target}",
            url=url,
            snippet=self._snippet(
                _clean(item.get("description")),
                version,
                downloads,
                "Verified" if verified else "",
            ),
            source="registry.terraform.io",
            rank=rank,
            provider=self.name,
            published_date=self._iso_date_prefix(
                _clean(item.get("published_at")) or None,
            ),
            extra={
                "kind": "module",
                "namespace": namespace,
                "name": name,
                "target_provider": target,
                "version": version,
                "downloads": downloads,
                "verified": verified,
                "source_repository": _clean(item.get("source")) or None,
            },
        )

    def _provider_result(self, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a provider search hit."""
        namespace = _clean(item.get("namespace"))
        name = _clean(item.get("name"))
        if not (namespace and name):
            return None

        version = _clean(item.get("version"))
        downloads = self._downloads(item.get("downloads"))
        tier = _clean(item.get("tier"))
        url = f"{_PROVIDER_PAGE_URL}{quote(namespace)}/{quote(name)}"
        if version:
            url = f"{url}/{quote(version)}"

        return SearchResult(
            title=f"{namespace}/{name}",
            url=url,
            snippet=self._snippet(
                _clean(item.get("description")),
                version,
                downloads,
                tier.title() if tier else "",
            ),
            source="registry.terraform.io",
            rank=rank,
            provider=self.name,
            published_date=self._iso_date_prefix(
                _clean(item.get("published_at")) or None,
            ),
            extra={
                "kind": "provider",
                "namespace": namespace,
                "name": name,
                "alias": _clean(item.get("alias")) or None,
                "version": version,
                "tier": tier,
                "downloads": downloads,
                "source_repository": _clean(item.get("source")) or None,
            },
        )

    @staticmethod
    def _entries(data: object, key: str) -> list[dict[str, Any]]:
        """Return the list of hit objects stored under *key* in *data*."""
        if not isinstance(data, dict):
            return []
        items = data.get(key)
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    def _parse(
        self,
        data: object,
        key: str,
        builder: Any,
        limit: int,
    ) -> list[SearchResult]:
        """Parse a Terraform Registry search response into ranked results."""
        results: list[SearchResult] = []
        for item in self._entries(data, key):
            if len(results) >= limit:
                break
            result = builder(item, len(results) + 1)
            if result is not None:
                results.append(result)
        return results

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the Terraform Registry for modules and providers.

        Both endpoints are queried concurrently; the merged, interleaved result
        set is capped at the requested number of results.  A failure on one
        endpoint degrades gracefully to the other, and only an error from both
        is raised.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        async def _fetch(url: str) -> object:
            async with self._client() as client:
                resp = await client.get(
                    url,
                    params={"q": cleaned, "limit": str(limit), "offset": "0"},
                )
                resp.raise_for_status()
                return resp.json()

        payloads = await asyncio.gather(
            _fetch(_MODULES_URL),
            _fetch(_PROVIDERS_URL),
            return_exceptions=True,
        )
        failures = [p for p in payloads if isinstance(p, Exception)]
        if len(failures) == len(payloads):
            raise failures[0]

        modules_data, providers_data = payloads
        modules = self._parse(
            modules_data,
            "modules",
            self._module_result,
            limit,
        )
        providers_ = self._parse(
            providers_data,
            "providers",
            self._provider_result,
            limit,
        )

        merged: list[SearchResult] = []
        for pair in zip_longest(modules, providers_):
            for result in pair:
                if result is None:
                    continue
                result.rank = len(merged) + 1
                merged.append(result)
                if len(merged) >= limit:
                    return ProviderResult(results=merged)
        return ProviderResult(results=merged)
