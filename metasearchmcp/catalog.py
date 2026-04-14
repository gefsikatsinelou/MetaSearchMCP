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
