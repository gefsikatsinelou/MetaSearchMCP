"""Unit tests for the Launch Library 2 space launch search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.spacelaunch import SpaceLaunchProvider


def _payload() -> dict:
    """A realistic ``/2.2.0/launch/?search=...`` API response."""
    return {
        "count": 2,
        "next": None,
        "previous": None,
        "results": [
            {
                "id": "d50b84e3-59c8-46ca-9b7d-fc30ad8b0d5d",
                "slug": "falcon-heavy-demo-test-flight",
                "name": "Falcon Heavy | Demo (Test Flight)",
                "net": "2018-02-06T20:45:00Z",
                "status": {
                    "id": 3,
                    "name": "Launch Successful",
                    "abbrev": "Success",
                },
                "launch_service_provider": {"id": 121, "name": "SpaceX"},
                "rocket": {
                    "configuration": {
                        "id": 164,
                        "full_name": "Falcon Heavy",
                    },
                },
                "mission": {
                    "id": 290,
                    "name": "Demo (Test Flight)",
                    "description": (
                        "Maiden flight of the Falcon Heavy, carrying Elon "
                        "Musk's Tesla Roadster into a heliocentric orbit."
                    ),
                    "type": "Test Flight",
                    "orbit": {"id": 6, "name": "Heliocentric orbit"},
                },
                "pad": {
                    "id": 87,
                    "name": "Launch Complex 39A",
                    "location": {"id": 12, "name": "Kennedy Space Center, FL, USA"},
                },
                "image": {
                    "image_url": "https://thespacedevs-prod.nyc3.digitaloceanspaces.com/media/images/falcon2520heavy_image_20230724161922.jpeg",
                },
            },
            {
                "id": "f46c3a8e-11c8-46bf-b1c4-0c5d2cbfe6b5",
                "slug": "saturn-v-apollo-11",
                "name": "Saturn V | Apollo 11",
                "net": "1969-07-16T13:32:00Z",
                "status": {
                    "id": 3,
                    "name": "Launch Successful",
                    "abbrev": "Success",
                },
                "launch_service_provider": {"id": 82, "name": "NASA"},
                "rocket": {"configuration": {"id": 92, "full_name": "Saturn V"}},
                "mission": {
                    "id": 627,
                    "name": "Apollo 11",
                    "description": (
                        "First crewed lunar landing mission; Armstrong and "
                        "Aldrin walked on the Moon."
                    ),
                    "type": "Lunar Exploration",
                    "orbit": {"id": 9, "name": "Lunar orbit"},
                },
                "pad": {
                    "id": 81,
                    "name": "Launch Complex 39A",
                    "location": {"id": 12, "name": "Kennedy Space Center, FL, USA"},
                },
                "image": None,
            },
        ],
    }


def _provider() -> SpaceLaunchProvider:
    return SpaceLaunchProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "spacelaunch"
    assert p.tags == ["space", "science"]
    assert "no API key required" in p.description


def test_parse_basic_hit_fields() -> None:
    p = _provider()
    result = p._parse(_payload())

    assert len(result.results) == 2
    first = result.results[0]
    assert first.title == "Falcon Heavy | Demo (Test Flight)"
    assert (
        first.url == "https://spacelaunchnow.me/launch/falcon-heavy-demo-test-flight/"
    )
    assert first.source == "spacelaunchnow.me"
    assert first.provider == "spacelaunch"
    assert first.rank == 1
    assert "Maiden flight of the Falcon Heavy" in first.snippet
    assert "Date: 2018-02-06" in first.snippet
    assert "Rocket: Falcon Heavy" in first.snippet
    assert "Status: Success" in first.snippet
    assert "Orbit: Heliocentric orbit" in first.snippet
    assert "Pad: Launch Complex 39A (Kennedy Space Center, FL, USA)" in first.snippet
    assert "Agency: SpaceX" in first.snippet
    assert first.extra["type"] == "launch"
    assert first.extra["rocket"] == "Falcon Heavy"
    assert first.extra["mission_name"] == "Demo (Test Flight)"
    assert first.extra["image_url"].startswith("https://")

    second = result.results[1]
    assert second.rank == 2
    assert second.title == "Saturn V | Apollo 11"
    assert "Lunar orbit" in second.snippet
    assert second.extra["image_url"] == ""


def test_parse_skips_entries_without_name() -> None:
    p = _provider()
    payload = {
        "results": [
            {"slug": "no-name-launch", "name": "Rocket | Good Hit", "net": None},
            {"slug": "nameless", "status": {"abbrev": "TBD"}},
            "junk",  # type: ignore[list-item]
            {"name": "", "slug": "empty-title"},
        ],
    }
    result = p._parse(payload)
    assert len(result.results) == 1
    hit = result.results[0]
    assert hit.title == "Rocket | Good Hit"
    # No mission metadata -> snippet carries no leading separators.
    assert hit.snippet == ""
    assert hit.extra["status"] == ""


def test_parse_handles_missing_optional_blocks() -> None:
    p = _provider()
    payload = {
        "results": [
            {
                "name": "Mystery Rocket | Unknown Mission",
                "slug": "mystery-rocket-unknown-mission",
                "url": "https://ll.thespacedevs.com/2.2.0/launch/123/",
                "net": "2026-01-15T00:00:00Z",
                "status": None,
                "rocket": {"configuration": None},
                "mission": None,
                "pad": None,
            }
        ]
    }
    result = p._parse(payload)
    assert len(result.results) == 1
    hit = result.results[0]
    assert "Date: 2026-01-15" in hit.snippet
    assert "Rocket:" not in hit.snippet
    assert hit.extra["rocket"] == ""
    assert hit.extra["pad"] == ""
    assert hit.extra["status"] == ""


def test_parse_url_falls_back_to_api_url_without_slug() -> None:
    p = _provider()
    payload = {
        "results": [
            {
                "name": "Rocket | No Slug",
                "url": "https://ll.thespacedevs.com/2.2.0/launch/42/",
            }
        ]
    }
    hit = p._parse(payload).results[0]
    assert hit.url == "https://ll.thespacedevs.com/2.2.0/launch/42/"


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse({"results": []}).results == []
    assert p._parse({}).results == []
    assert p._parse({"results": None}).results == []
    assert p._parse(None).results == []
    assert p._parse("junk").results == []


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse(_payload(), limit=1).results) == 1


def test_clean_snippet_truncates_long_description() -> None:
    p = _provider()
    payload = {
        "results": [
            {
                "name": "Rocket | Long Mission",
                "slug": "rocket-long-mission",
                "mission": {"description": "word " * 500},
            }
        ]
    }
    snippet = p._parse(payload).results[0].snippet
    assert len(snippet) <= 400
    assert snippet.startswith("word word")


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock) -> None:
    import respx

    respx_mock.get("https://ll.thespacedevs.com/2.2.0/launch/").mock(
        return_value=respx.MockResponse(200, json=_payload()),
    )

    p = _provider()
    result = await p.search("falcon heavy", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "spacelaunch"
    assert result.results[0].title == "Falcon Heavy | Demo (Test Flight)"
    assert result.results[1].rank == 2

    call = respx_mock.calls[0].request
    assert call.url.path.endswith("/2.2.0/launch/")
    assert call.url.params["search"] == "falcon heavy"
    assert call.url.params["limit"] == "5"


@pytest.mark.asyncio
async def test_search_no_hits_returns_empty(respx_mock) -> None:
    import respx

    respx_mock.get("https://ll.thespacedevs.com/2.2.0/launch/").mock(
        return_value=respx.MockResponse(200, json={"count": 0, "results": []}),
    )

    p = _provider()
    result = await p.search("zzqqxxyy", SearchParams(num_results=5))

    assert result.results == []
