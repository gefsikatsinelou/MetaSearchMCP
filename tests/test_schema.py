"""Tests for request and response contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from metasearchmcp.contracts import (
    ProviderReport,
    SearchHit,
    SearchOptions,
    SearchEnvelope,
    SearchReport,
)


def test_search_result_derives_source_from_url():
    r = SearchHit(title="Test", url="https://example.com/page", provider="test")
    assert r.source == "example.com"


def test_search_result_keeps_explicit_source():
    r = SearchHit(
        title="Test", url="https://example.com/page", source="Custom", provider="test"
    )
    assert r.source == "Custom"


def test_search_result_empty_url_ok():
    r = SearchHit(title="Test", url="", provider="test")
    assert r.source == ""


def test_search_params_defaults():
    p = SearchOptions()
    assert p.num_results == 10
    assert p.language == "en"
    assert p.safe_search is True


def test_search_params_bounds():
    with pytest.raises(ValidationError):
        SearchOptions(num_results=0)
    with pytest.raises(ValidationError):
        SearchOptions(num_results=51)


def test_search_request_requires_query():
    with pytest.raises(ValidationError):
        SearchEnvelope(query="")


def test_search_request_defaults():
    req = SearchEnvelope(query="hello world")
    assert req.providers == []
    assert req.tags == []
    assert req.params.num_results == 10


def test_search_response_serializable():
    resp = SearchReport(
        query="test",
        results=[
            SearchHit(title="A", url="https://a.com", provider="p1"),
        ],
        timing_ms=42.0,
        providers=[
            ProviderReport(name="p1", success=True, result_count=1, latency_ms=42.0)
        ],
    )
    data = resp.model_dump()
    assert data["query"] == "test"
    assert len(data["results"]) == 1
    assert data["results"][0]["provider"] == "p1"


def test_provider_status_failed():
    ps = ProviderReport(name="bad", success=False, error="timeout")
    assert ps.result_count == 0
    assert ps.error == "timeout"
