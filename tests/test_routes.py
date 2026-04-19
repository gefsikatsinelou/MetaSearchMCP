from __future__ import annotations

from types import SimpleNamespace

from metasearchmcp import __version__
from metasearchmcp.api.routes import _build_tag_groups


def test_build_tag_groups_sorts_tags_and_provider_names():
    registry = {
        "github": SimpleNamespace(name="github", tags=["code", "web"]),
        "arxiv": SimpleNamespace(name="arxiv", tags=["academic", "web"]),
        "dockerhub": SimpleNamespace(name="dockerhub", tags=["containers", "code"]),
    }

    groups = _build_tag_groups(registry)

    assert list(groups.keys()) == ["academic", "code", "containers", "web"]
    assert groups["code"] == ["dockerhub", "github"]
    assert groups["web"] == ["arxiv", "github"]


def test_version_string_is_exposed_for_health_metadata():
    assert isinstance(__version__, str)
    assert __version__ == "0.1.0"


def test_health_payload_shape_example():
    registry = {
        "github": SimpleNamespace(name="github", tags=["code", "web"]),
        "arxiv": SimpleNamespace(name="arxiv", tags=["academic", "web"]),
    }

    payload = {
        "status": "ok",
        "version": __version__,
        "provider_count": len(registry),
        "providers": sorted(registry.keys()),
    }

    assert payload["provider_count"] == 2
    assert payload["providers"] == ["arxiv", "github"]
