"""Tests for active provider health probes and the /health/providers route."""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar
from unittest.mock import patch

from fastapi.testclient import TestClient

from metasearchmcp.api import routes
from metasearchmcp.contracts import ProviderPayload, SearchHit
from metasearchmcp.health import probe_provider, probe_providers
from metasearchmcp.providers.base import BaseProvider
from metasearchmcp.server import app


class FakeProvider(BaseProvider):
    """Minimal provider whose behaviour is controlled by the test."""

    tags: ClassVar[list[str]] = ["web"]

    def __init__(
        self,
        name: str,
        *,
        result_count: int = 1,
        error: Exception | None = None,
        delay: float = 0.0,
        available: bool = True,
        calls: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.name = name
        self.description = f"{name} fake provider"
        self._result_count = result_count
        self._error = error
        self._delay = delay
        self._available = available
        self._calls = calls if calls is not None else []

    async def search(self, query: str, params: Any) -> ProviderPayload:
        """Record the query and return configured results, error, or delay."""
        self._calls.append(query)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return ProviderPayload(
            results=[
                SearchHit(
                    title=f"{self.name} hit {idx}",
                    url=f"https://example.com/{self.name}/{idx}",
                )
                for idx in range(self._result_count)
            ],
        )

    def is_available(self) -> bool:
        """Return the configured availability flag."""
        return self._available


def make_provider(
    name: str,
    *,
    tags: tuple[str, ...] = ("web",),
    **kwargs: Any,
) -> FakeProvider:
    """Build a fake provider whose class-level tags match *tags*."""
    cls = type("FakeProviderWithTags", (FakeProvider,), {"tags": list(tags)})
    return cls(name, **kwargs)


async def test_probe_provider_reports_ok_and_latency():
    calls: list[str] = []
    provider = FakeProvider("alpha", result_count=2, calls=calls)

    entry = await probe_provider(provider, "hello", timeout_seconds=5.0)

    assert calls == ["hello"]
    assert entry["name"] == "alpha"
    assert entry["status"] == "ok"
    assert entry["available"] is True
    assert entry["result_count"] == 2
    assert entry["error"] is None
    assert entry["latency_ms"] >= 0.0
    assert entry["tags"] == ["web"]


async def test_probe_provider_captures_exceptions():
    provider = FakeProvider("broken", error=RuntimeError("upstream exploded"))

    entry = await probe_provider(provider)

    assert entry["status"] == "error"
    assert entry["error"] == "upstream exploded"
    assert entry["result_count"] == 0


async def test_probe_provider_marks_timeout():
    provider = FakeProvider("slow", delay=0.2)

    entry = await probe_provider(provider, timeout_seconds=0.01)

    assert entry["status"] == "timeout"
    assert "timeout" in entry["error"]


async def test_probe_provider_skips_unavailable_without_calling_search():
    calls: list[str] = []
    provider = FakeProvider("keyless_disabled", available=False, calls=calls)

    entry = await probe_provider(provider)

    assert calls == []
    assert entry["status"] == "unavailable"
    assert entry["available"] is False
    assert entry["error"] is None


async def test_probe_providers_summarises_and_caps_probe_count():
    providers = [
        FakeProvider("charlie"),
        FakeProvider("alpha", result_count=3),
        FakeProvider("bravo", error=ValueError("nope")),
        FakeProvider("delta", available=False),
    ]

    summary = await probe_providers(providers, max_providers=3)

    assert summary["status"] == "degraded"
    assert summary["total"] == 4
    assert summary["probed"] == 3
    assert summary["ok_count"] == 2
    assert summary["failed_count"] == 1
    assert summary["unavailable_count"] == 0
    # Providers are probed in name order; the tail is reported as skipped.
    assert [entry["name"] for entry in summary["providers"]] == [
        "alpha",
        "bravo",
        "charlie",
    ]
    assert summary["skipped"] == ["delta"]


async def test_probe_providers_ok_when_only_unavailable_remain():
    providers = [FakeProvider("alpha"), FakeProvider("beta", available=False)]

    summary = await probe_providers(providers)

    assert summary["status"] == "ok"
    assert summary["ok_count"] == 1
    assert summary["unavailable_count"] == 1
    assert summary["failed_count"] == 0


def test_health_providers_route_returns_probe_report():
    catalog = {
        "alpha": FakeProvider("alpha", result_count=2),
        "bravo": FakeProvider("bravo", available=False),
    }

    with patch.object(routes, "_catalog", catalog), TestClient(app) as client:
        response = client.get(
            "/health/providers",
            params={"providers": ["alpha", "bravo"], "q": "python", "timeout": 1},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "python"
    assert body["probed"] == 2
    assert body["ok_count"] == 1
    assert body["unavailable_count"] == 1
    assert body["failed_count"] == 0
    assert {entry["name"] for entry in body["providers"]} == {"alpha", "bravo"}


def test_health_providers_route_respects_limit():
    catalog = {
        "alpha": FakeProvider("alpha"),
        "bravo": FakeProvider("bravo"),
        "charlie": FakeProvider("charlie"),
    }

    with patch.object(routes, "_catalog", catalog), TestClient(app) as client:
        response = client.get("/health/providers", params={"limit": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["probed"] == 2
    assert body["skipped"] == ["charlie"]


def test_health_providers_route_unknown_provider_returns_503():
    catalog = {"alpha": FakeProvider("alpha")}

    with patch.object(routes, "_catalog", catalog), TestClient(app) as client:
        response = client.get("/health/providers", params={"providers": ["missing"]})

    assert response.status_code == 503


def test_health_providers_route_filters_by_tag():
    catalog = {
        "alpha": make_provider("alpha", tags=("web",)),
        "beta": make_provider("beta", tags=("academic",)),
    }

    with patch.object(routes, "_catalog", catalog), TestClient(app) as client:
        response = client.get("/health/providers", params={"tag": "academic"})

    assert response.status_code == 200
    body = response.json()
    assert body["probed"] == 1
    assert body["providers"][0]["name"] == "beta"
