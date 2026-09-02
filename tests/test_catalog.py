"""Tests for provider catalog filtering utilities."""

from __future__ import annotations

from types import SimpleNamespace

from metasearchmcp.catalog import (
    pick_first_provider,
    pick_named_providers,
    pick_providers_by_tags,
    pick_tagged_providers,
)
from metasearchmcp.providers.registry import build_registry


def test_pick_providers_by_tags_returns_all_when_empty():
    catalog = {
        "duckduckgo": SimpleNamespace(tags=["web", "privacy"]),
        "github": SimpleNamespace(tags=["code", "web"]),
    }

    assert pick_providers_by_tags(catalog, []) == catalog


def test_pick_providers_by_tags_matches_any_requested_tag():
    catalog = {
        "duckduckgo": SimpleNamespace(tags=["web", "privacy"]),
        "github": SimpleNamespace(tags=["code", "web"]),
        "arxiv": SimpleNamespace(tags=["academic"]),
    }

    filtered = pick_providers_by_tags(catalog, ["academic", "privacy"])

    assert list(filtered.keys()) == ["duckduckgo", "arxiv"]


def test_pick_providers_by_tags_can_require_all_requested_tags():
    catalog = {
        "duckduckgo": SimpleNamespace(tags=["web", "privacy"]),
        "github": SimpleNamespace(tags=["code", "web"]),
        "npm": SimpleNamespace(tags=["code", "web", "packages"]),
    }

    filtered = pick_providers_by_tags(catalog, ["code", "packages"], match="all")

    assert list(filtered.keys()) == ["npm"]


def test_pick_named_providers_normalizes_case_and_deduplicates():
    catalog = {
        "duckduckgo": SimpleNamespace(tags=["web"]),
        "github": SimpleNamespace(tags=["code", "web"]),
        "npm": SimpleNamespace(tags=["code", "packages"]),
    }

    filtered = pick_named_providers(catalog, [" GitHub ", "NPM", "github", " "])

    assert list(filtered.keys()) == ["github", "npm"]


def test_pick_providers_by_tags_normalizes_case_and_deduplicates():
    catalog = {
        "duckduckgo": SimpleNamespace(tags=["web", "privacy"]),
        "github": SimpleNamespace(tags=["code", "web"]),
        "npm": SimpleNamespace(tags=["code", "web", "packages"]),
    }

    filtered = pick_providers_by_tags(
        catalog,
        [" Code ", "PACKAGES", "code"],
        match="all",
    )

    assert list(filtered.keys()) == ["npm"]


def test_pick_tagged_providers_matches_any_requested_tag():
    catalog = {
        "duckduckgo": SimpleNamespace(tags=["web", "privacy"]),
        "arxiv": SimpleNamespace(tags=["academic", "web"]),
        "github": SimpleNamespace(tags=["code", "web"]),
    }

    filtered = pick_tagged_providers(catalog, "privacy")

    assert list(filtered.keys()) == ["duckduckgo"]


def test_pick_tagged_providers_unknown_tag_yields_empty():
    catalog = {
        "duckduckgo": SimpleNamespace(tags=["web"]),
    }

    assert pick_tagged_providers(catalog, "nonexistent") == {}


def test_pick_tagged_providers_is_case_insensitive():
    catalog = {
        "arxiv": SimpleNamespace(tags=["academic", "web"]),
    }

    assert list(pick_tagged_providers(catalog, "ACADEMIC").keys()) == ["arxiv"]


def test_pick_first_provider_returns_single_entry():
    catalog = {
        "duckduckgo": SimpleNamespace(tags=["web"]),
        "github": SimpleNamespace(tags=["code"]),
    }

    first = pick_first_provider(catalog)

    assert list(first.keys()) == ["duckduckgo"]


def test_pick_first_provider_empty_catalog():
    assert pick_first_provider({}) == {}


def test_pick_first_provider_preserves_instance():
    catalog = {
        "duckduckgo": SimpleNamespace(tags=["web"]),
    }

    assert pick_first_provider(catalog) == catalog


def test_registry_catalog_is_nonempty_and_complete():
    """Every registered provider exposes a name, description, and tags."""
    catalog = build_registry()

    assert len(catalog) >= 90
    for name, provider in catalog.items():
        assert provider.name == name
        assert provider.description
        assert provider.tags
