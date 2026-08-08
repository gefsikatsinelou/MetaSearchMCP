"""Unit tests for the Hugging Face Hub model search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.providers.huggingface import HuggingFaceProvider

_SAMPLE_RESPONSE = [
    {
        "id": "openai/whisper-large-v3",
        "likes": 6111,
        "private": False,
        "downloads": 5253587,
        "pipeline_tag": "automatic-speech-recognition",
        "library_name": "transformers",
        "gated": False,
        "lastModified": "2024-03-11T10:00:00.000Z",
        "tags": ["transformers", "pytorch", "whisper", "en"],
    },
    {
        "id": "sentence-transformers/all-MiniLM-L6-v2",
        "likes": 50000,
        "downloads": 123456789,
        "pipeline_tag": "feature-extraction",
        "library_name": "sentence-transformers",
        "gated": "auto",
    },
    {
        "id": "minimal/model",
    },
    "not-a-dict",
    {"id": "  ", "downloads": 1},
]


def test_huggingface_parse_basic():
    p = HuggingFaceProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 3
    r = result.results[0]
    assert r.title == "openai/whisper-large-v3"
    assert r.url == "https://huggingface.co/openai/whisper-large-v3"
    assert "Task: automatic-speech-recognition" in r.snippet
    assert "Library: transformers" in r.snippet
    assert "Downloads: 5,253,587" in r.snippet
    assert r.source == "huggingface.co"
    assert r.provider == "huggingface"
    assert r.rank == 1
    assert r.published_date == "2024-03-11"
    assert r.extra["downloads"] == 5253587
    assert r.extra["likes"] == 6111
    assert r.extra["gated"] is False


def test_huggingface_parse_second_item():
    p = HuggingFaceProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    r = result.results[1]
    assert r.url == "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2"
    assert r.published_date is None
    assert r.extra["gated"] is True
    assert r.extra["downloads"] == 123456789


def test_huggingface_parse_skips_invalid_entries():
    p = HuggingFaceProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    # Fourth entry is not a dict; fifth has a blank id.
    assert all(r.url for r in result.results)
    assert len(result.results) == 3
    # A minimal entry (no metadata) still yields a valid result with empty snippet.
    r = result.results[2]
    assert r.title == "minimal/model"
    assert r.url == "https://huggingface.co/minimal/model"
    assert r.snippet == ""
    assert r.extra["downloads"] == 0


def test_huggingface_parse_empty_and_non_list():
    p = HuggingFaceProvider()
    assert p._parse([]).results == []
    assert p._parse(None).results == []
    assert p._parse({}).results == []
    assert p._parse("oops").results == []


def test_huggingface_model_url():
    assert (
        HuggingFaceProvider._model_url("openai/whisper-large-v3")
        == "https://huggingface.co/openai/whisper-large-v3"
    )
    assert HuggingFaceProvider._model_url("") == ""


def test_huggingface_is_available():
    """Keyless provider is always available."""
    assert HuggingFaceProvider().is_available() is True


@pytest.mark.asyncio
async def test_huggingface_search_builds_query(respx_mock):
    """The search method hits the Hub API and parses the response."""
    import respx

    respx_mock.get("https://huggingface.co/api/models").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    from metasearchmcp.contracts import SearchParams

    p = HuggingFaceProvider()
    result = await p.search("whisper", SearchParams(num_results=5))

    assert len(result.results) == 3
    assert result.results[0].provider == "huggingface"
    assert result.results[0].url == "https://huggingface.co/openai/whisper-large-v3"
