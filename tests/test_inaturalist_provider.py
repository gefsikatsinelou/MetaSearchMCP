"""Unit tests for the iNaturalist biodiversity observation search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.inaturalist import INaturalistProvider


def _sample_response() -> dict:
    return {
        "total_results": 3,
        "results": [
            {
                "id": 396043054,
                "species_guess": "Orca",
                "uri": "https://www.inaturalist.org/observations/396043054",
                "observed_on": "2015-07-07",
                "quality_grade": "research",
                "taxon": {
                    "name": "Orcinus orca",
                    "rank": "species",
                    "iconic_taxon_name": "Mammalia",
                    "preferred_common_name": "Orca",
                },
                "user": {"login": "orca_watcher"},
                "place": {"display_name": "Bremer Bay, WA, AU"},
                "photos": [
                    {
                        "url": "https://inaturalist-open-data.s3.amazonaws.com/photos/1/square.jpeg",
                        "medium_url": "https://inaturalist-open-data.s3.amazonaws.com/photos/1/medium.jpeg",
                    },
                    {
                        "url": "https://inaturalist-open-data.s3.amazonaws.com/photos/2/square.jpeg",
                    },
                ],
            },
            {
                "id": 123,
                "species_guess": "Humpback Whale",
                "uri": "https://www.inaturalist.org/observations/123",
                "observed_on": "2026-08-01T10:00:00Z",
                "taxon": {
                    "name": "Megaptera novaeangliae",
                    "iconic_taxon_name": "Mammalia",
                },
                "user": {"login": "whale_fan"},
                "place": {},
                "photos": [],
            },
            {
                # Missing species guess -> skipped.
                "id": 999,
                "uri": "https://www.inaturalist.org/observations/999",
                "taxon": {},
                "user": {},
                "place": {},
                "photos": [],
            },
            "not-a-dict",
            None,
        ],
    }


def test_parse_basic():
    p = INaturalistProvider()
    result = p._parse(_sample_response())

    # Invalid items (missing species guess, non-dict) are skipped.
    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Orca"
    assert r.url == "https://www.inaturalist.org/observations/396043054"
    assert r.provider == "inaturalist"
    assert r.source == "inaturalist.org"
    assert r.rank == 1
    assert r.published_date == "2015-07-07"
    assert r.extra["scientific_name"] == "Orcinus orca"
    assert r.extra["iconic_taxon"] == "Mammalia"
    assert r.extra["observer"] == "orca_watcher"
    assert r.extra["place"] == "Bremer Bay, WA, AU"
    assert r.extra["image_url"].endswith("/photos/1/medium.jpeg")
    assert r.extra["thumbnail_url"].endswith("/photos/1/medium.jpeg")
    assert len(r.extra["photos"]) == 2
    assert "Orcinus orca (Mammalia)" in r.snippet
    assert "Bremer Bay" in r.snippet
    assert "orca_watcher" in r.snippet


def test_parse_second_result_rank_and_no_photos():
    p = INaturalistProvider()
    result = p._parse(_sample_response())
    r = result.results[1]
    assert r.rank == 2
    assert r.title == "Humpback Whale"
    assert r.published_date == "2026-08-01"
    assert "image_url" not in r.extra
    assert "photos" not in r.extra


def test_parse_empty_and_non_dict():
    p = INaturalistProvider()
    assert p._parse({}).results == []
    assert p._parse({"results": []}).results == []
    assert p._parse(None).results == []
    assert p._parse([]).results == []


def test_parse_respects_limit():
    p = INaturalistProvider()
    result = p._parse(_sample_response(), limit=1)
    assert len(result.results) == 1
    assert result.results[0].title == "Orca"


def test_is_available():
    """Keyless provider is always available."""
    assert INaturalistProvider().is_available() is True


@pytest.mark.asyncio
async def test_search_hits_api_and_parses(respx_mock):
    import respx

    respx_mock.get(
        "https://api.inaturalist.org/v1/observations",
        params={"q": "orca", "per_page": "5"},
    ).mock(
        return_value=respx.MockResponse(200, json=_sample_response()),
    )

    p = INaturalistProvider()
    result = await p.search("orca", SearchParams(num_results=5))

    assert len(result.results) == 2
    assert result.results[0].provider == "inaturalist"
    assert result.results[0].title == "Orca"
    assert result.results[0].url.startswith("https://www.inaturalist.org/observations/")


def test_photo_urls_handles_garbage():
    assert INaturalistProvider._photo_urls(None) == []
    assert INaturalistProvider._photo_urls("nope") == []
    assert INaturalistProvider._photo_urls([{"url": "https://x/1.jpg"}]) == [
        "https://x/1.jpg"
    ]
    assert INaturalistProvider._photo_urls([{"medium_url": "https://x/m.jpg"}]) == [
        "https://x/m.jpg"
    ]
