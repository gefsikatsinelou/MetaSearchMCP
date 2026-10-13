"""Unit tests for the Civitai AI-model search provider."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.civitai import CivitaiProvider

_ENDPOINT = "https://civitai.com/api/v1/models"
_MODEL_ID = 144249

_MODEL: dict[str, Any] = {
    "id": _MODEL_ID,
    "name": "AniMerge",
    "description": "An anime checkpoint.",
    "type": "Checkpoint",
    "nsfw": False,
    "tags": [
        "girls",
        "anime",
        "semirealistic",
        "base model",
        "comics",
        "cartoon",
    ],
    "creator": {
        "username": "Samael1976",
        "image": "https://image.civitai.com/x/width=96/Samael1976.jpeg",
    },
    "stats": {
        "downloadCount": 86434,
        "thumbsUpCount": 6452,
        "thumbsDownCount": 7,
        "commentCount": 0,
        "tippedAmountCount": 48658,
    },
    "modelVersions": [
        {
            "id": 495273,
            "name": "V5.0",
            "baseModel": "SD 1.5",
            "trainedWords": [],
            "publishedAt": "2024-06-30T22:00:00.000Z",
            "downloadUrl": "https://civitai.com/api/download/models/495273",
            "stats": {"downloadCount": 50000},
            "images": [
                {
                    "url": "https://image.civitai.com/x/preview.jpeg",
                    "nsfwLevel": 1,
                    "width": 512,
                    "height": 512,
                }
            ],
        }
    ],
}

_ADULT: dict[str, Any] = {
    "id": 999,
    "name": "Adult LoRA",
    "type": "LORA",
    "nsfw": True,
    "tags": [],
    "stats": {"downloadCount": 12},
    "modelVersions": [],
}

_SPARSE: dict[str, Any] = {"id": 5}

_BASE_MODELS_FALLBACK: dict[str, Any] = {
    "id": 7,
    "name": "",
    "baseModels": ["SDXL 1.0", "Pony"],
    "modelVersions": [],
}


def _envelope(records: list[Any]) -> dict[str, Any]:
    """Wrap *records* in a Civitai search response envelope."""
    return {
        "items": records,
        "metadata": {
            "nextCursor": "2",
            "nextPage": "https://civitai.com/api/v1/models?cursor=2",
        },
    }


def test_civitai_name_tags_and_availability() -> None:
    p = CivitaiProvider()
    assert p.name == "civitai"
    assert p.tags == ["image", "media", "ai"]
    assert p.is_available() is True
    assert "No API key required" in p.description


def test_civitai_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "civitai" in registry
    assert registry["civitai"].tags == ["image", "media", "ai"]


def test_civitai_parse_record() -> None:
    p = CivitaiProvider()
    result = p._parse(_envelope([_MODEL]), limit=5)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "AniMerge"
    assert r.url == f"https://civitai.com/models/{_MODEL_ID}"
    assert r.source == "civitai.com"
    assert r.provider == "civitai"
    assert r.rank == 1
    assert r.published_date == "2024-06-30"
    assert r.snippet == (
        "Checkpoint | SD 1.5 | 86,434 downloads | 6,452 likes | "
        "girls anime semirealistic base model comics | by Samael1976"
    )
    assert r.extra["civitai_id"] == _MODEL_ID
    assert r.extra["type"] == "Checkpoint"
    assert r.extra["nsfw"] is False
    assert r.extra["creator"] == "Samael1976"
    assert r.extra["tags"] == [
        "girls",
        "anime",
        "semirealistic",
        "base model",
        "comics",
        "cartoon",
    ]
    assert r.extra["download_count"] == 86434
    assert r.extra["thumbs_up"] == 6452
    assert r.extra["thumbs_down"] == 7
    assert r.extra["comment_count"] == 0
    assert r.extra["base_model"] == "SD 1.5"
    assert r.extra["latest_version"] == "V5.0"
    assert r.extra["version_id"] == 495273
    assert r.extra["trained_words"] == []
    assert r.extra["version_download_count"] == 50000
    assert r.extra["download_url"] == ("https://civitai.com/api/download/models/495273")
    assert r.extra["preview_image"] == "https://image.civitai.com/x/preview.jpeg"


def test_civitai_marks_adult_records() -> None:
    p = CivitaiProvider()
    r = p._parse(_envelope([_ADULT])).results[0]

    assert r.title == "Adult LoRA"
    assert r.extra["nsfw"] is True
    assert r.extra["type"] == "LORA"
    assert r.snippet == "LORA | 12 downloads"
    assert r.extra["latest_version"] is None
    assert r.extra["base_model"] is None
    assert r.extra["preview_image"] is None
    assert r.published_date is None


def test_civitai_sparse_record_falls_back_to_identifier() -> None:
    p = CivitaiProvider()
    r = p._parse(_envelope([_SPARSE])).results[0]

    assert r.title == "Civitai model 5"
    assert r.url == "https://civitai.com/models/5"
    assert r.snippet == ""
    assert r.published_date is None
    assert r.extra["type"] is None
    assert r.extra["creator"] is None
    assert r.extra["base_model"] is None
    assert r.extra["download_count"] is None
    assert r.extra["preview_image"] is None
    assert r.extra["tags"] == []


def test_civitai_base_model_falls_back_to_model_list() -> None:
    p = CivitaiProvider()
    r = p._parse(_envelope([_BASE_MODELS_FALLBACK])).results[0]

    assert r.title == "Civitai model 7"
    assert r.extra["base_model"] == "SDXL 1.0"
    assert r.snippet == "SDXL 1.0"


def test_civitai_parse_skips_records_without_id() -> None:
    p = CivitaiProvider()
    payload = _envelope([{}, {"id": "5"}, "nope", _MODEL])
    results = p._parse(payload).results
    assert [r.extra["civitai_id"] for r in results] == [_MODEL_ID]
    assert results[0].rank == 1


def test_civitai_parse_respects_limit() -> None:
    p = CivitaiProvider()
    payload = _envelope([_MODEL, _ADULT, _SPARSE])
    assert len(p._parse(payload, limit=2).results) == 2
    assert len(p._parse(payload).results) == 3


def test_civitai_parse_empty_and_malformed() -> None:
    p = CivitaiProvider()
    assert p._parse(_envelope([])).results == []
    assert p._parse({}).results == []
    assert p._parse({"items": "nope"}).results == []
    assert p._parse({"items": [1, 2, 3]}).results == []
    assert p._parse({"error": "Not Found"}).results == []
    assert p._parse([1, 2, 3]).results == []
    assert p._parse(None).results == []


def test_civitai_parse_ignores_odd_field_types() -> None:
    p = CivitaiProvider()
    payload = _envelope(
        [
            {
                "id": 9,
                "name": 42,
                "type": None,
                "tags": ["a", 7, ""],
                "stats": {"downloadCount": "many", "thumbsUpCount": True},
                "creator": "nope",
                "modelVersions": "nope",
            }
        ]
    )
    r = p._parse(payload).results[0]

    assert r.title == "Civitai model 9"
    assert r.snippet == "a"
    assert r.extra["type"] is None
    assert r.extra["creator"] is None
    assert r.extra["tags"] == ["a"]
    assert r.extra["download_count"] is None
    assert r.extra["thumbs_up"] is None
    assert r.extra["latest_version"] is None


def test_civitai_helpers() -> None:
    from metasearchmcp.providers.civitai import (
        _base_model,
        _clean,
        _int,
        _label,
        _latest_version,
        _preview_image,
        _strings,
        _username,
    )

    assert _clean("  a\n  b  ") == "a b"
    assert _clean(None) == ""
    assert _int(86434) == 86434
    assert _int(True) is None
    assert _int("86434") is None
    assert _strings(["a", 7, "", "b"]) == ["a", "b"]
    assert _strings("nope") == []
    assert _username({"username": " bob "}) == "bob"
    assert _username("nope") == ""
    assert _label("Checkpoint") == "Checkpoint"
    assert _label(None) == ""
    assert _latest_version({"modelVersions": [{"id": 1}]}) == {"id": 1}
    assert _latest_version({"modelVersions": ["x", {"id": 2}]}) == {"id": 2}
    assert _latest_version({"modelVersions": "nope"}) == {}
    assert _latest_version({}) == {}
    assert _base_model({}, {"baseModel": "SD 1.5"}) == "SD 1.5"
    assert _base_model({"baseModels": ["SDXL"]}, {}) == "SDXL"
    assert _base_model({}, {}) == ""
    assert _preview_image({"images": [{"url": " https://x/a.jpg "}]}) == (
        "https://x/a.jpg"
    )
    assert _preview_image({"images": [{"url": ""}, {"url": "https://x/b.jpg"}]}) == (
        "https://x/b.jpg"
    )
    assert _preview_image({"images": "nope"}) == ""
    assert _preview_image({}) == ""


async def test_civitai_search_sends_expected_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope([_MODEL, _ADULT]))
    )

    result = await CivitaiProvider().search(
        "anime",
        SearchParams(num_results=5),
    )

    assert route.called
    params = route.calls[0].request.url.params
    assert params["query"] == "anime"
    assert params["limit"] == "5"
    assert params["sort"] == "Most Downloaded"
    assert params["nsfw"] == "false"

    assert [r.extra["civitai_id"] for r in result.results] == [_MODEL_ID, 999]


async def test_civitai_search_requests_adult_entries(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope([_ADULT]))
    )

    await CivitaiProvider().search("anime", SearchParams(safe_search=False))

    assert route.calls[0].request.url.params["nsfw"] == "true"


async def test_civitai_search_respects_result_limits(respx_mock) -> None:
    records = [dict(_MODEL, id=n) for n in range(60)]
    respx_mock.get(_ENDPOINT).mock(
        return_value=respx.MockResponse(200, json=_envelope(records))
    )

    provider = CivitaiProvider()
    provider._max_results = 1000
    result = await provider.search("anime", SearchParams(num_results=50))
    assert len(result.results) == 50

    provider._max_results = 1
    result = await provider.search("anime", SearchParams(num_results=50))
    assert len(result.results) == 1


async def test_civitai_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_ENDPOINT)

    result = await CivitaiProvider().search("   ", SearchParams())

    assert result.results == []
    assert not route.called


async def test_civitai_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_ENDPOINT).mock(return_value=respx.MockResponse(500))

    with pytest.raises(httpx.HTTPStatusError):
        await CivitaiProvider().search("anime", SearchParams())
