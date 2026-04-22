from __future__ import annotations

from metasearchmcp.providers.base import BaseProvider
from metasearchmcp.providers.registry import build_registry


def build_provider_catalog() -> dict[str, BaseProvider]:
    return build_registry()


def pick_named_providers(
    catalog: dict[str, BaseProvider],
    names: list[str],
) -> dict[str, BaseProvider]:
    if not names:
        return catalog
    return {name: catalog[name] for name in names if name in catalog}


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
    if not tags:
        return catalog

    requested = set(tags)
    require_all = match == "all"
    return {
        name: provider
        for name, provider in catalog.items()
        if (
            requested.issubset(provider.tags)
            if require_all
            else bool(requested.intersection(provider.tags))
        )
    }
