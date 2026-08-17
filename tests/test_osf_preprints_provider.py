"""Unit tests for the OSF Preprints search provider."""

from __future__ import annotations

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.osf_preprints import OSFPreprintsProvider

_SAMPLE_ATTRIBUTES: dict[str, object] = {
    "title": "A validity-guided workflow for robust language model research",
    "description": (
        "Large language models are rapidly being integrated into "
        "psychological research. This preprint outlines a six-stage workflow."
    ),
    "doi": "10.31234/osf.io/abc123",
    "date_published": "2026-07-01T07:00:00",
    "custom_publication_citation": (
        "Lin, Z. (2026). A validity-guided workflow for robust language "
        "model research in psychology. PsyArXiv."
    ),
    "subjects": [
        [{"id": "x1", "text": "Meta-science"}],
        [{"id": "x2", "text": "Social and Behavioral Sciences"}],
    ],
}

_SAMPLE_ITEM: dict[str, object] = {
    "id": "abc123",
    "type": "preprints",
    "attributes": _SAMPLE_ATTRIBUTES,
    "links": {
        "self": "https://api.osf.io/v2/preprints/abc123/",
        "html": "https://osf.io/preprints/psyarxiv/abc123/",
        "preprint_doi": "https://doi.org/10.31234/osf.io/abc123",
    },
}

_SAMPLE_RESPONSE: dict[str, object] = {"data": [_SAMPLE_ITEM]}

_EMPTY_RESPONSE: dict[str, object] = {"data": []}


def test_osf_preprints_parse_basic():
    p = OSFPreprintsProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "A validity-guided workflow for robust language model research"
    assert r.url == "https://osf.io/preprints/psyarxiv/abc123/"
    assert "six-stage workflow" in r.snippet
    assert "Subjects: Meta-science, Social and Behavioral Sciences" in r.snippet
    assert r.source == "osf.io"
    assert r.provider == "osf_preprints"
    assert r.rank == 1
    assert r.published_date == "2026-07-01"
    assert r.extra["doi"] == "10.31234/osf.io/abc123"
    assert r.extra["subjects"] == ["Meta-science", "Social and Behavioral Sciences"]
    assert "Lin, Z. (2026)" in r.extra["citation"]


def test_osf_preprints_parse_uses_doi_link_when_html_missing():
    item = {
        "id": "abc123",
        "attributes": {
            "title": "Preprint without landing page",
            "doi": "10.31234/osf.io/xyz789",
        },
        "links": {"preprint_doi": "https://doi.org/10.31234/osf.io/xyz789"},
    }
    result = OSFPreprintsProvider()._parse({"data": [item]})
    assert len(result.results) == 1
    assert result.results[0].url == "https://doi.org/10.31234/osf.io/xyz789"


def test_osf_preprints_parse_empty():
    p = OSFPreprintsProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_osf_preprints_parse_non_dict():
    p = OSFPreprintsProvider()
    assert p._parse([]).results == []
    assert p._parse({"data": None}).results == []


def test_osf_preprints_parse_skips_items_without_title():
    bad_item = {"attributes": {"description": "no title here"}}
    result = OSFPreprintsProvider()._parse({"data": [bad_item]})
    assert result.results == []


def test_osf_preprints_parse_deduplicates_subjects():
    attributes = {
        "title": "Dup subjects",
        "subjects": [[{"text": "Physics"}], [{"text": "Physics"}]],
    }
    result = OSFPreprintsProvider()._parse({"data": [{"attributes": attributes}]})
    assert result.results[0].extra["subjects"] == ["Physics"]


def test_osf_preprints_search_builds_filter_params(monkeypatch):
    p = OSFPreprintsProvider()
    captured: dict[str, object] = {}

    class FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": [{"attributes": {"title": "x"}}]}

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, params: dict[str, object]) -> FakeResp:
            captured["url"] = url
            captured["params"] = params
            return FakeResp()

    monkeypatch.setattr(p, "_client", lambda: FakeClient())

    import asyncio

    params = SearchParams(num_results=5)
    result = asyncio.run(p.search("neural networks", params))

    assert captured["url"] == "https://api.osf.io/v2/preprints"
    assert captured["params"] == {"filter[title]": "neural networks", "page[size]": "5"}
    assert len(result.results) == 1
    assert result.results[0].provider == "osf_preprints"


def test_osf_preprints_default_tags():
    assert "academic" in OSFPreprintsProvider.tags
    assert "preprints" in OSFPreprintsProvider.tags
