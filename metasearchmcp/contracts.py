"""Pydantic data models for search requests, results, and reports."""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator


class SearchHit(BaseModel):
    """Normalized result item returned by any provider."""

    title: str
    url: str
    snippet: str = ""
    source: str = ""
    rank: int = 0
    provider: str = ""
    published_date: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def derive_source(self) -> SearchHit:
        """Derive the source domain from the URL when not explicitly set."""
        if not self.source and self.url:
            self.source = urlparse(self.url).netloc or ""
        return self


class ProviderPayload(BaseModel):
    """Container for raw results returned by a single provider."""

    results: list[SearchHit] = Field(default_factory=list)
    related_searches: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    answer_box: dict[str, Any] | None = None


class ProviderReport(BaseModel):
    """Metadata about a single provider's execution outcome."""

    name: str
    success: bool
    result_count: int = 0
    latency_ms: float = 0.0
    error: str | None = None


class SearchOptions(BaseModel):
    """Common search parameters shared across providers and endpoints."""

    num_results: int = Field(default=10, ge=1, le=50)
    max_total_results: int = Field(default=20, ge=1, le=100)
    language: str = "en"
    country: str = "us"
    safe_search: bool = True


class SearchEnvelope(BaseModel):
    """Request body for the aggregate /search endpoint."""

    query: str = Field(..., min_length=1, max_length=500)
    providers: list[str] = Field(
        default_factory=list,
        description="Explicit provider list; empty = use all enabled providers",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Optional provider tags used to narrow the provider set",
    )
    tag_match: Literal["any", "all"] = Field(
        default="any",
        description="How tag filters are applied: match any tag or require all tags",
    )
    params: SearchOptions = Field(default_factory=SearchOptions)


class GoogleSearchEnvelope(BaseModel):
    """Request body for the Google-specific /search/google endpoint."""

    query: str = Field(..., min_length=1, max_length=500)
    provider: str = Field(
        default="",
        description=(
            "'google', 'google_serpbase', or 'google_serper'; empty = first available"
        ),
    )
    params: SearchOptions = Field(default_factory=SearchOptions)


class SearchReport(BaseModel):
    """Unified response returned by all search endpoints."""

    engine: str = "metasearchmcp"
    query: str
    results: list[SearchHit]
    related_searches: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    answer_box: dict[str, Any] | None = None
    timing_ms: float
    providers: list[ProviderReport]
    errors: list[str] = Field(default_factory=list)


# Backwards-compatible aliases for the older module naming.
SearchResult = SearchHit
ProviderResult = ProviderPayload
ProviderStatus = ProviderReport
SearchParams = SearchOptions
SearchRequest = SearchEnvelope
GoogleSearchRequest = GoogleSearchEnvelope
SearchResponse = SearchReport
