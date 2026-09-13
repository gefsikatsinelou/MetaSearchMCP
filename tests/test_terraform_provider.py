"""Unit tests for the Terraform Registry provider."""

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.terraform import TerraformRegistryProvider

_MODULES_URL = "https://registry.terraform.io/v1/modules"
_PROVIDERS_URL = "https://registry.terraform.io/v1/providers"

_MODULES_PAYLOAD = {
    "meta": {"limit": 10, "current_offset": 0, "next_offset": 10},
    "modules": [
        {
            "id": "terraform-aws-modules/vpc/aws/6.0.1",
            "owner": "",
            "namespace": "terraform-aws-modules",
            "name": "vpc",
            "version": "6.0.1",
            "provider": "aws",
            "description": "Terraform module which creates VPC resources on AWS",
            "source": "https://github.com/terraform-aws-modules/terraform-aws-vpc",
            "tag": "v6.0.1",
            "published_at": "2026-03-11T10:00:00Z",
            "downloads": 123456789,
            "verified": True,
        },
        {
            "namespace": "Azure",
            "name": "aks",
            "version": "9.0.0",
            "provider": "azurerm",
            "description": "",
            "downloads": "not-a-number",
            "verified": False,
            "published_at": None,
        },
        {"namespace": "broken", "name": "no-target"},
        "not a mapping",
    ],
}

_PROVIDERS_PAYLOAD = {
    "meta": {"limit": 10, "current_offset": 0, "next_offset": 10},
    "providers": [
        {
            "id": "hashicorp/aws/6.0.0",
            "namespace": "hashicorp",
            "name": "aws",
            "alias": None,
            "version": "6.0.0",
            "tag": "v6.0.0",
            "description": "terraform-provider-aws",
            "source": "https://github.com/hashicorp/terraform-provider-aws",
            "published_at": "2026-09-02T09:49:41Z",
            "downloads": 4180000000,
            "tier": "official",
        },
        {"namespace": "hashicorp", "name": "no-version"},
        {},
    ],
}


def _mock_both(respx_mock) -> None:
    """Mock both registry endpoints with the shared sample payloads."""
    respx_mock.get(_MODULES_URL).mock(
        return_value=respx.MockResponse(200, json=_MODULES_PAYLOAD),
    )
    respx_mock.get(_PROVIDERS_URL).mock(
        return_value=respx.MockResponse(200, json=_PROVIDERS_PAYLOAD),
    )


def _provider() -> TerraformRegistryProvider:
    """Return a fresh provider instance for each test."""
    return TerraformRegistryProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "terraform"
    assert p.tags == ["web", "code", "developer", "packages"]
    assert "no API key required" in p.description
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "terraform" in registry
    assert registry["terraform"].tags == ["web", "code", "developer", "packages"]


@pytest.mark.asyncio
async def test_search_builds_module_results(respx_mock) -> None:
    _mock_both(respx_mock)

    result = await _provider().search("vpc", SearchParams(num_results=10))
    module = result.results[0]

    assert module.title == "terraform-aws-modules/vpc/aws"
    assert module.url == (
        "https://registry.terraform.io/modules/terraform-aws-modules/vpc/aws/6.0.1"
    )
    assert module.source == "registry.terraform.io"
    assert module.provider == "terraform"
    assert module.published_date == "2026-03-11"
    assert module.snippet.startswith("Terraform module which creates VPC resources")
    assert "v6.0.1" in module.snippet
    assert "Downloads: 123,456,789" in module.snippet
    assert "Verified" in module.snippet
    assert module.extra == {
        "kind": "module",
        "namespace": "terraform-aws-modules",
        "name": "vpc",
        "target_provider": "aws",
        "version": "6.0.1",
        "downloads": 123456789,
        "verified": True,
        "source_repository": (
            "https://github.com/terraform-aws-modules/terraform-aws-vpc"
        ),
    }


@pytest.mark.asyncio
async def test_search_builds_provider_results(respx_mock) -> None:
    _mock_both(respx_mock)

    result = await _provider().search("aws", SearchParams(num_results=10))
    provider = result.results[1]

    assert provider.title == "hashicorp/aws"
    assert provider.url == "https://registry.terraform.io/providers/hashicorp/aws/6.0.0"
    assert provider.snippet == (
        "terraform-provider-aws | v6.0.0 | Downloads: 4,180,000,000 | Official"
    )
    assert provider.published_date == "2026-09-02"
    assert provider.extra["kind"] == "provider"
    assert provider.extra["tier"] == "official"
    assert provider.extra["alias"] is None
    assert provider.extra["downloads"] == 4180000000


@pytest.mark.asyncio
async def test_search_interleaves_and_ranks_results(respx_mock) -> None:
    _mock_both(respx_mock)

    result = await _provider().search("aws", SearchParams(num_results=10))

    assert [r.title for r in result.results] == [
        "terraform-aws-modules/vpc/aws",
        "hashicorp/aws",
        "Azure/aks/azurerm",
        "hashicorp/no-version",
    ]
    assert [r.rank for r in result.results] == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_search_skips_incomplete_and_malformed_entries(respx_mock) -> None:
    _mock_both(respx_mock)

    result = await _provider().search("aws", SearchParams(num_results=10))
    titles = [r.title for r in result.results]

    # The module without a target provider, the bare string and the empty
    # provider object produce no results.
    assert "broken/no-target" not in titles
    assert len(result.results) == 4

    fallback = next(r for r in result.results if r.title == "Azure/aks/azurerm")
    assert (
        fallback.url == "https://registry.terraform.io/modules/Azure/aks/azurerm/9.0.0"
    )
    assert fallback.published_date is None
    assert fallback.extra["downloads"] == 0
    assert "Downloads" not in fallback.snippet
    assert "Verified" not in fallback.snippet


@pytest.mark.asyncio
async def test_search_respects_limit(respx_mock) -> None:
    _mock_both(respx_mock)

    result = await _provider().search("aws", SearchParams(num_results=2))

    assert [r.title for r in result.results] == [
        "terraform-aws-modules/vpc/aws",
        "hashicorp/aws",
    ]
    assert [r.rank for r in result.results] == [1, 2]


@pytest.mark.asyncio
async def test_search_sends_query_params(respx_mock) -> None:
    modules_route = respx_mock.get(_MODULES_URL).mock(
        return_value=respx.MockResponse(200, json=_MODULES_PAYLOAD),
    )
    providers_route = respx_mock.get(_PROVIDERS_URL).mock(
        return_value=respx.MockResponse(200, json=_PROVIDERS_PAYLOAD),
    )

    await TerraformRegistryProvider().search(
        "kubernetes cluster",
        SearchParams(num_results=4),
    )

    for route in (modules_route, providers_route):
        params = route.calls.last.request.url.params
        assert params["q"] == "kubernetes cluster"
        assert params["limit"] == "4"
        assert params["offset"] == "0"


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    modules_route = respx_mock.get(_MODULES_URL).mock(
        return_value=respx.MockResponse(200, json=_MODULES_PAYLOAD),
    )
    providers_route = respx_mock.get(_PROVIDERS_URL).mock(
        return_value=respx.MockResponse(200, json=_PROVIDERS_PAYLOAD),
    )

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not modules_route.called
    assert not providers_route.called


@pytest.mark.asyncio
async def test_search_tolerates_single_endpoint_failure(respx_mock) -> None:
    respx_mock.get(_MODULES_URL).mock(return_value=respx.MockResponse(500))
    respx_mock.get(_PROVIDERS_URL).mock(
        return_value=respx.MockResponse(200, json=_PROVIDERS_PAYLOAD),
    )

    result = await _provider().search("aws", SearchParams(num_results=5))

    assert [r.title for r in result.results] == [
        "hashicorp/aws",
        "hashicorp/no-version",
    ]


@pytest.mark.asyncio
async def test_search_raises_when_both_endpoints_fail(respx_mock) -> None:
    respx_mock.get(_MODULES_URL).mock(return_value=respx.MockResponse(503))
    respx_mock.get(_PROVIDERS_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await TerraformRegistryProvider().search("aws", SearchParams(num_results=5))


@pytest.mark.asyncio
async def test_search_handles_unexpected_payload_shapes(respx_mock) -> None:
    respx_mock.get(_MODULES_URL).mock(
        return_value=respx.MockResponse(200, json={"modules": "nope"}),
    )
    respx_mock.get(_PROVIDERS_URL).mock(
        return_value=respx.MockResponse(200, json=["not", "a", "mapping"]),
    )

    result = await _provider().search("aws", SearchParams(num_results=5))

    assert result.results == []
