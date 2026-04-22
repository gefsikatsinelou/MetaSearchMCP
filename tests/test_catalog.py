from __future__ import annotations

from types import SimpleNamespace

from metasearchmcp.catalog import pick_providers_by_tags


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
