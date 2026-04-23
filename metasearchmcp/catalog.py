from __future__ import annotations

from metasearchmcp.providers.base import BaseProvider
from metasearchmcp.providers.registry import build_registry


def _normalize_requested_values(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip().lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def build_provider_catalog() -> dict[str, BaseProvider]:
    return build_registry()


def pick_named_providers(
    catalog: dict[str, BaseProvider],
    names: list[str],
) -> dict[str, BaseProvider]:
    normalized_names = _normalize_requested_values(names)
    if not normalized_names:
        return catalog
    return {
        name: provider
        for name, provider in catalog.items()
        if name.lower() in normalized_names
    }


def pick_tagged_providers(
    catalog: dict[str, BaseProvider],
    tag: str,
) -> dict[str, BaseProvider]:
    return {
        name: provider for name, provider in catalog.items() if tag in provider.tags
    }


def pick_providers_by_tags(
    catalog: dict[str, BaseProvider],
    tags: list[str],
    match: str = "any",
) -> dict[str, BaseProvider]:
    requested_tags = _normalize_requested_values(tags)
    if not requested_tags:
        return catalog

    requested = set(requested_tags)
    require_all = match == "all"
    return {
        name: provider
        for name, provider in catalog.items()
        if (
            requested.issubset({tag.lower() for tag in provider.tags})
            if require_all
            else bool(requested.intersection({tag.lower() for tag in provider.tags}))
        )
    }
